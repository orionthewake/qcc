# python3
"""Amplitude Estimation."""

import math
import random

from absl import app
from typing import List, Tuple
import numpy as np

from src.lib import helper
from src.lib import ops
from src.lib import state


# Amplitude estimation (AE) is a generalization of the counting
# algorithm (or, rather, counting is a special case of AE).
#
# In counting, we have a state in equal superposition
# (achieved via Hadamard^\otimes(nbits) where some of the states
# are 'good' and the rest are 'bad.
#
# In the general case, the probabilities for each state can be
# different. A general algorithm A generates a state. Then, similar
# to grover, one can think of the space that the orthogonal good
# and bad states span as:
#     \psi = \alpha \psi_{good} + \beta \psi_{bad}
#
# AE estimates this amplitude \alpha.


def make_f(nbits: int = 3, solutions: List[int] = [0]):
  """Construct function that will return 1 for 'solutions' bits."""

  answers = np.zeros(1 << nbits, dtype=np.int32)
  answers[solutions] = 1
  return lambda bits : answers[helper.bits2val(bits)]


def run_experiment(nbits_phase: int,
                   nbits_grover: int,
                   algo: ops.Operator,
                   solutions: List[int]) -> None:
  """Run full experiment for a given A and set of solutions."""

  # The state for the AE algorithm.
  # We reserve nbits_phase for the phase estimation.
  # We reserve nbits_grover for the oracle.
  # We also add the |1> for the oracle's y value.
  #
  # These numbers can be adjusted to achieve various levels
  # of accuracy.
  psi = state.zeros(nbits_phase + nbits_grover) * state.ones(1)

  # Apply Hadamard to all the qubits.
  for i in range(nbits_phase + nbits_grover + 1):
    psi.apply1(ops.Hadamard(), i)

  # Construct the Grover operator. First phase invesion via Oracle.
  f = make_f(nbits_grover, solutions)
  u = ops.OracleUf(nbits_grover + 1, f)

  # Reflection over mean.
  op_zero = ops.ZeroProjector(nbits_grover)
  reflection = op_zero * 2.0 - ops.Identity(nbits_grover)

  # Now construct the combined Grover operator.
  inversion = algo.adjoint()(reflection(algo)) * ops.Identity()
  grover = inversion(u)

  # Now that we have the Grover operator, we have to perform
  # phase estimation. This loop is a copy from phase_estimation.py
  # (with more comments there).
  cu = grover
  for inv in range(nbits_phase - 1, -1, -1):
    psi = ops.ControlledU(inv, nbits_phase, cu)(psi, inv)
    cu = cu(cu)

  # Reverse QFT gives us the phase as a fraction of 2*pi.
  psi = ops.Qft(nbits_phase).adjoint()(psi)

  # Get the state with highest probability and estimate a phase
  maxbits, maxprob = psi.maxprob()
  ampl = np.sin(np.pi * helper.bits2frac(maxbits))

  print('  AE: {:.4f} prob: {:6.2f}% {}/{} solutions ({})'
        .format(ampl, ampl * ampl * 100, len(solutions),
        1 << nbits_grover, solutions))
  return ampl


def main(argv):
  if len(argv) > 1:
    raise app.UsageError('Too many command-line arguments.')
  print('Amplitude Estimation...')

  print('Algorithm: Hadamard (equal superposition)')
  algorithm = ops.Hadamard(3)

  for nsolutions in range(5):
    ampl = run_experiment(7, 3, algorithm,
                          random.sample(range(2**3-1), nsolutions))
    if not math.isclose(ampl, np.sqrt(nsolutions / 2**3), abs_tol=0.03):
      raise AssertionError('Incorrect AE.')

  # Make a somewhat random algorithm (and state)
  print('Algorithm: Random (unequal superposition), single solution')
  algorithm = (ops.Hadamard(3) @
               (ops.RotationY(random.random()/2) * ops.Identity(2)) @
               (ops.Identity(1) * ops.RotationY(0.2) * ops.Identity(1)) @
               (ops.Identity(2) * ops.RotationY(random.random()/2)))
  psi = algorithm(state.zeros(3))

  for i in range(len(psi)):
    ampl = run_experiment(7, 3, algorithm, [i])

  print('Algorithm: Random (unequal superposition), multiple solutions')
  for i in range(len(psi)+1):
    ampl = run_experiment(7, 3, algorithm, [i for i in range(i)])


if __name__ == '__main__':
  app.run(main)