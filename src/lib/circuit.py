# python3
# pylint: disable=invalid-name

"""class qc (quantum circuit) represents state and operators."""


from __future__ import annotations

from typing import Callable, Tuple

from absl import flags
import numpy as np
from scipy.linalg import sqrtm
from scipy.stats import unitary_group
from src.lib import dumpers
from src.lib import ir
from src.lib import ops
from src.lib import state
from src.lib import tensor


# Many of the algorithm implementation rely on the fast performance
# provided by libxgates. However, it can be difficult to build,
# depending on your environment. To enable a quick start on this codebase
# we provide Python fallback functions. They work, but are slow.
#
# Configure: The following line might have to change, depending on
#            the current build environment.
# Google internal:
# import xgates
#
# GitHub / Linux:
# import libxgates as xgates


try:
  # pylint: disable=g-import-not-at-top
  import libxgates as xgates

  apply1 = xgates.apply1
  applyc = xgates.applyc
except Exception:  # pylint: disable=broad-except
  print("""
  **************************************************************
  WARNING: Could not find 'libxgates.so'.
  Please build it and point PYTHONPATH to it.
  Execution is being re-directed to a Python implementation,
  performance may suffer greatly.
  **************************************************************
  """)

  # pylint: disable=unused-argument
  def apply1(psi, gate: np.ndarray, nbits: int, qubit: int, bitwidth: int = 0):
    return psi.apply1(gate.reshape((2, 2)), qubit)

  # pylint: disable=unused-argument
  def applyc(psi, gate, nbits, control, target, bitwidth=0):
    return psi.applyc(gate.reshape((2, 2)), control, target)


flags.DEFINE_string('libq', '', 'Generate libq output file, or empty')
flags.DEFINE_string('qasm', '', 'Generate qasm output file, or empty')
flags.DEFINE_string('cirq', '', 'Generate cirq output file, or empty')
flags.DEFINE_string('text', '', 'Generate text output file, or empty')
flags.DEFINE_string('latex', '', 'Generate Latex output file, or empty')


class qc:
  """Wrapper class to maintain state + operators."""

  def __init__(self, name=None, eager: bool = True):
    self.name = name
    self.psi = state.State(1.0)
    self.ir = ir.Ir()
    self.eager = eager
    self.build_ir = not eager
    self.global_reg = 0
    self.sub_circuits = 0

    try:  # this can fail in python-only REPL environements.
      if (flags.FLAGS.libq + flags.FLAGS.qasm + flags.FLAGS.cirq +
          flags.FLAGS.text + flags.FLAGS.latex):
        self.eager = False
    except Exception:  # pylint: disable=broad-except
      pass

    self.simple_gates = [
        ['h', ops.Hadamard()],
        ['s', ops.Sgate()],
        ['t', ops.Tgate()],
        ['v', ops.Vgate()],
        ['x', ops.PauliX()],
        ['y', ops.PauliY()],
        ['z', ops.PauliZ()],
        ['yroot', ops.Yroot()],
    ]
    for gate in self.simple_gates:
      self.add_single(gate[0], gate[1])
      self.add_single(gate[0] + 'dag', gate[1].adjoint())
      self.add_ctl('c' + gate[0], gate[1])
      self.add_ctl('c' + gate[0] + 'dag', gate[1].adjoint())

  @property
  def nbits(self) -> int:
    return self.psi.nbits

  class scope:
    """Scope object to allow grouping of gates in the output."""

    def __init__(self, ir_param, desc: str):
      self.ir = ir_param
      self.desc = desc

    def __enter__(self):
      self.ir.section(self.desc)

    def __exit__(self, t, value, traceback):
      self.ir.end_section()

  # --- States ----------------------------------------------------
  def _tprod(self, new_state, nqubits: int):
    self.psi = self.psi * new_state
    self.global_reg = self.global_reg + nqubits

  def reg(self, size: int, it=0, *, name: str = None) -> state.Reg:
    ret = state.Reg(size, it, self.global_reg)
    self._tprod(ret.psi(), size)
    self.ir.reg(size, name, ret)
    return ret

  def qubit(self, alpha: np.complexfloating = None,
            beta: np.complexfloating = None) -> None:
    self._tprod(state.qubit(alpha, beta), 1)

  def zeros(self, n: int) -> None:
    self._tprod(state.zeros(n), n)

  def ones(self, n: int) -> None:
    self._tprod(state.ones(n), n)

  def bitstring(self, *bits: Tuple[int, ...]) -> None:
    self._tprod(state.bitstring(*bits), len(bits))

  def rand_bits(self, n: int) -> None:
    self._tprod(state.rand_bits(n), n)

  def arange(self, n: int) -> None:
    self.psi = state.State([float(i) for i in range(0, 2**n)])
    self.global_reg = self.global_reg + n

  def random(self, n: int = 1) -> None:
    u = ops.Operator(unitary_group.rvs(1 << n))
    self.psi = u(state.zeros(n))

  # We know we can initialize any state, eg., with the code
  # found in src/state_prep_mottonen.py. Here, we take a
  # shortcut and just assign the intended state to a
  # register and return that register.
  def state(self, t: tensor.Tensor) -> None:
    psi = state.State(t)
    ret = state.Reg(t.nbits, 0, self.global_reg)
    self._tprod(psi, psi.nbits)
    self.ir.reg(t.nbits, 'state', ret)
    return ret

  def _ctl_by_0(self, ctl):
    if isinstance(ctl, int):
      return ctl, False
    return ctl[0], True

  # --- Gates  ----------------------------------------------------
  def add_single(self, name: str, gate: ops.Operator):
    setattr(self, name, lambda idx, cond=True:
            self.apply1(gate, idx, name) if cond else None)

  def add_ctl(self, name: str, gate: ops.Operator):
    setattr(self, name, lambda idx0, idx1, cond=True:
            self.applyc(gate, idx0, idx1, name) if cond else None)

  def apply1(
      self, gate: ops.Operator, idx_set, name: str = None, *, val: float = None
  ):
    """Apply single gates."""

    indices = []
    if isinstance(idx_set, int):
      indices.append(idx_set)
    if isinstance(idx_set, (state.Reg, list)):
      indices += idx_set[:]

    for idx in indices:
      if self.build_ir:
        self.ir.single(name, idx, gate, val)
      if self.eager:
        assert idx < self.psi.nbits, 'Invalid qubit index'
        apply1(self.psi, gate.reshape(4), self.psi.nbits, idx,
               tensor.tensor_width())

  def applyc(self, gate: ops.Operator, ctl: int, idx: int,
             name: str = None, *, val: float = None):
    """Apply controlled gates."""

    if isinstance(idx, state.Reg):
      assert len(idx) == 1, 'Controlled n-qbit register not supported'
      idx = idx[0]

    ctl_qubit, by_0 = self._ctl_by_0(ctl)
    self.x(ctl_qubit, by_0)
    if self.build_ir:
      self.ir.controlled(name, ctl_qubit, idx, gate, val)
    if self.eager:
      assert idx < self.psi.nbits, 'Invalid qubit index'
      applyc(self.psi, gate.reshape(4), self.psi.nbits, ctl_qubit, idx,
             tensor.tensor_width())
    self.x(ctl_qubit, by_0)

  def cx0(self, idx0: int, idx1: int):
    xgate = ops.PauliX()
    self.apply1(xgate, idx0, 'x')
    self.applyc(ops.PauliX(), idx0, idx1, 'cx')
    self.apply1(xgate, idx0, 'x')

  def cu(self, idx0: int, idx1: int, op: ops.Operator, desc: str = None):
    assert op.shape[0] == 2, 'cu only supports 2x2 operators'
    self.applyc(op, idx0, idx1, desc)

  def ccu(self, idx0: int, idx1: int, idx2: int, op: ops.Operator, desc=''):
    """Sleator-Weinfurter Construction for general operators."""

    # Enable Control-By-0 (if idx is being passes as [idx])
    i0, c0_by_0 = self._ctl_by_0(idx0)
    i1, c1_by_0 = self._ctl_by_0(idx1)

    with self.scope(self.ir, f'CC{op.name}\\{desc}({idx0},{idx1},{idx2})'):
      self.x(i0, c0_by_0)
      self.x(i1, c1_by_0)

      v = ops.Operator(sqrtm(op))
      self.cu(i0, idx2, v, op.name + '^{1/2}')
      self.cx(i0, i1)
      self.cu(i1, idx2, v.adjoint(), op.name + '^t')
      self.cx(i0, i1)
      self.cu(i1, idx2, v, op.name + '^{1/2}')

      self.x(i1, c1_by_0)
      self.x(i0, c0_by_0)

  def ccx(self, idx0: int, idx1: int, idx2: int):
    self.ccu(idx0, idx1, idx2, ops.PauliX(), 'ccx')

  def toffoli(self, idx0: int, idx1: int, idx2: int):
    self.ccu(idx0, idx1, idx2, ops.PauliX(), 'ccx')

  def u1(self, idx: int, val):
    self.apply1(ops.U1(val), idx, 'u1', val=val)

  def cu1(self, idx0: int, idx1: int, value):
    self.applyc(ops.U1(value), idx0, idx1, 'cu1', val=value)

  def ccu1(self, idx0: int, idx1: int, tgt:int, value):
    self.ccu(idx0, idx1, tgt, ops.U1(value))

  def rx(self, idx: int, theta: float):
    self.apply1(ops.RotationX(theta), idx, 'rx', val=theta)

  def ry(self, idx: int, theta: float):
    self.apply1(ops.RotationY(theta), idx, 'ry', val=theta)

  def rz(self, idx: int, theta: float):
    self.apply1(ops.RotationZ(theta), idx, 'rz', val=theta)

  def crx(self, ctl: int, idx: int, theta: float):
    self.applyc(ops.RotationX(theta), ctl, idx, 'crx', val=theta)

  def cry(self, ctl: int, idx: int, theta: float):
    self.applyc(ops.RotationY(theta), ctl, idx, 'cry', val=theta)

  def crz(self, ctl: int, idx: int, theta: float):
    self.applyc(ops.RotationZ(theta), ctl, idx, 'crz', val=theta)

  #  Appplying a random unitary is possible, but it is not a
  #  1- or 2-qubit gate, hence slow. Avoid using it (unless unavoidable).
  def unitary(self, op, idx):
    self.psi = ops.Operator(op)(self.psi, idx)

  # --- Measure ----------------------------------------------------
  def measure_bit(self, idx: int, tostate: int = 0,
                  collapse: bool = True) -> Tuple[float, state.State]:
    """Measure state with big matrix operation, can collapse the state."""

    prob, self.psi = ops.Measure(self.psi, idx, tostate, collapse)
    return prob, self.psi

  def pauli_expectation(self, idx: int):
    """We can compute the Pauli expectation value from probabilities."""

    # Pauli eigenvalues are -1 and +1, hence we can compute the
    # expectation value like this:
    p0, _ = self.measure_bit(idx, 0, False)
    return p0 - (1 - p0)

  # --- Advanced ---------------------------------------------------
  def swap(self, idx0: int, idx1: int):
    """Simple Swap operation."""

    # pylint: disable=arguments-out-of-order
    with self.scope(self.ir, f'swap({idx0}, {idx1})'):
      self.cx(idx1, idx0)
      self.cx(idx0, idx1)
      self.cx(idx1, idx0)

  def cswap(self, ctl, idx0, idx1):
    """Controlled Swap."""

    with self.scope(self.ir, f'cswap({ctl}, {idx0}, {idx1})'):
      self.cx(idx1, idx0)
      self.ccx(ctl, idx0, idx1)
      self.cx(idx1, idx0)

  def qft(self, reg, with_swaps: bool = False) -> None:
    """QFT."""

    for i in reversed(range(len(reg))):
      self.h(reg[i])
      for j in reversed(range(i)):
        self.cu1(reg[i], reg[j], np.pi/2**(i - j))
    if with_swaps:
      self.flip(reg)

  def inverse_qft(self, reg, with_swaps: bool = False) -> None:
    """Inverse QFT."""

    if with_swaps:
      self.flip(reg)
    for idx, r in enumerate(reg):
      self.h(r)
      if idx != len(reg) - 1:
        for y in range(idx, -1, -1):
          self.cu1(reg[idx + 1], reg[y], -np.pi / 2 ** (idx + 1 - y))

  def multi_control(self, ctl, idx1, aux, gate, desc: str = ''):
    """Multi-controlled gate, using aux as ancilla."""

    if aux:
      assert len(aux) >= len(ctl)-1, 'Incorrect number of ancilla qubits.'

    # This is a simple version that requires n-1 ancillaries, instead
    # of possibly n-2. The benefit is that the gate can be used as a
    # single-controlled gate, which means we don't need to take the
    # root (no need to include scipy). This construction also makes
    # the controlled-by-0 gates a little bit easier, those controllers
    # are being passed as single-element lists, eg.:
    #   ctl = [1, 2, [3], [4], 5]
    #
    # This can be optimized (later) to turn into a space-optimized
    # n-2 version.
    #
    # We also generalize to the case where ctl is empty or only has 1
    # control qubit. This is very flexible and practically any gate
    # could be expressed this way. This would make bulk control of
    # whole gate sequences straight-forward, but changes the trivial
    # IR we're working with here. Something to keep in mind.

    with self.scope(self.ir, f'multi-{gate.name}({ctl}, {idx1}) # {desc})'):
      if not ctl:
        self.apply1(gate, idx1, desc)
        return
      if isinstance(ctl, state.Reg):
        ctl = ctl[:]
      if len(ctl) == 1:
        self.applyc(gate, ctl[0], idx1, desc)
        return
      if len(ctl) == 2:
        self.ccu(ctl[0], ctl[1], idx1, gate, desc)
        return

      # Compute the predicate.
      self.ccx(ctl[0], ctl[1], aux[0])
      aux_idx = 0
      for i in range(2, len(ctl)):
        self.ccx(ctl[i], aux[aux_idx], aux[aux_idx + 1])
        aux_idx = aux_idx + 1

      # Use predicate to single-control qubit at idx1.
      self.applyc(gate, aux[aux_idx], idx1, desc)

      # Uncompute predicate.
      aux_idx = aux_idx - 1
      for i in range(len(ctl) - 1, 1, -1):
        self.ccx(ctl[i], aux[aux_idx], aux[aux_idx + 1])
        aux_idx = aux_idx - 1
      self.ccx(ctl[0], ctl[1], aux[0])

  def flip(self, reg: state.Reg):
    """Flip a quantum register via swaps."""

    for i in range(len(reg) // 2):
      self.swap(reg[i], reg[len(reg) - 1 - i])

  # --- qc of qc ------------------------------------------
  def qc(self, qc_parm: qc, offset=0):
    """Add another full circuit to this circuit."""

    # Iterate over the new circuit and add the gates one by one,
    # using this circuit's eager mode.
    #
    for gate in qc_parm.ir.gates:
      if gate.is_single():
        self.apply1(gate.gate, gate.idx0 + offset, gate.name, val=gate.val)
      if gate.is_ctl():
        self.applyc(gate.gate, gate.ctl + offset, gate.idx1 + offset,
                    gate.name, val=gate.val)

  def run(self):
    """Apply gates in this qc, don't rebuild IR."""

    build_ir = self.build_ir
    eager = self.eager
    self.build_ir = False
    self.eager = True
    self.qc(self)
    self.build_ir = build_ir
    self.eager = eager

  def inverse(self):
    """Return, but don't apply, the inverse circuit."""

    # The order of the gates is reversed and the each gates
    # itself becomes its adjoint. After this, a new circuit
    # is returned. Eager mode is False. The expectation
    # is that an inverse circuit inv is constructed and then applied
    # via circuit.qc(inv), at which point it is applied according to the
    # eager mode of the qc circuit. Usage model:
    #
    #    main = circuit.qc('main circuit')
    #    ... add gates, eager or not.
    #
    #    c = circuit.qc('sub circuit', eager=False)
    #    ... add gates to c, not eager.
    #
    #    Now let's add c to main, at which point the gates are applied.
    #      main.qc(c)
    #
    #    Let's construct the inverse (non-Eager) and add to main (eager)
    #    at an offset.
    #      c_inv = c0.inverse()
    #      main.qc(c_inv, offset=3)
    #
    newqc = qc(self.name, eager=False)
    for gate in self.ir.gates[::-1]:
      val = -gate.val if gate.val else None
      if gate.is_single():
        newqc.apply1(gate.gate.adjoint(), gate.idx0, gate.name + '*', val=val)
      if gate.is_ctl():
        newqc.applyc(
            gate.gate.adjoint(), gate.ctl, gate.idx1, gate.name + '*', val=val
        )
    return newqc

  def invert(self, reg):
    """Invert the circuit gates across a register reg."""

    def swap_bits(reg, idx):
      d = int(len(reg) - idx - 1)
      tmp = reg[idx]
      reg[idx] = reg[d]
      reg[d] = tmp

    for gate in self.ir.gates:
      swap_bits(reg, gate.idx0, reg.size)
      if gate.is_ctl():
        swap_bits(reg, gate.idx1, reg.size)

  def control_by(self, ctl: int):
    """Control a full circuit by qubit 'ctl'."""

    assert not self.eager, 'control_by() used in non-eager circuit.'
    res = ir.Ir()
    for _, gate in enumerate(self.ir.gates):
      if gate.is_single():
        gate.to_ctl(ctl)
        res.add_node(gate)
        continue
      if gate.is_ctl():
        sub = qc('multi', eager=False)
        sub.multi_control(
            [ctl, gate.ctl], gate.idx1, None, gate.gate, gate.desc
        )
        for gate in sub.ir.gates:
          res.add_node(gate)
    self.ir = res

  def sub(self, name: str = ''):
    """Make a subcircuit, which is a simple non-eager circuit."""

    sub = qc(f'inner_{self.sub_circuits}{name}', eager=False)
    self.sub_circuits += 1
    return sub

  # --- Debug --------------------------------------------------
  def stats(self) -> str:
    return (
        'Circuit Statistics\n'
        + '  Qubits: {}\n'.format(self.nbits)
        + '  Gates : {}\n'.format(self.ir.ngates)
    )

  def dump_with_dumper(self, flag: bool,
                       dumper_func: Callable[ir.Ir]) -> None:
    if flag:
      result = dumper_func(self.ir)
      with open(flag, 'w') as f:
        print(result, file=f)

  def dump_to_file(self) -> None:
    self.dump_with_dumper(flags.FLAGS.libq, dumpers.libq)
    self.dump_with_dumper(flags.FLAGS.qasm, dumpers.qasm)
    self.dump_with_dumper(flags.FLAGS.cirq, dumpers.cirq)
    self.dump_with_dumper(flags.FLAGS.text, dumpers.totext)
    self.dump_with_dumper(flags.FLAGS.latex, dumpers.latex)

  def dump(self, *, desc=None, draw=False, pstate=True):
    """Simple dumper for basic debugging of a circuit."""

    if desc:
      print(desc)
    if self.name:
      print(f'Circuit: {self.name}, Gates: {len(self.ir.gates)}, '
            + f'QBits: {self.psi.nbits}')
    print(self.ir, end='')
    if draw:
      print(dumpers.totext(self.ir))
    if pstate:
      self.psi.dump('Current state')
