# python3
"""Example: Order Finding - the precursor to Shor."""

# This code could not have been completed and debugged without looking
# and comparing to this working implementation (based on Qiskit):
#
#    https://github.com/ttlion/ShorAlgQiskit/blob/master/Shor_Normal_QFT.py
#
# Funny enough - even Qiskit mentions this implementation as a reference.
#
import fractions
import math

from absl import app
from absl import flags

from src.lib import circuit
from src.lib import helper

flags.DEFINE_integer('N', 15, 'Number to factor.')
flags.DEFINE_integer('a', 4, 'Start search with this number.')


def modular_inverse(a, m):
  """Compute Modular Inverse."""

  def egcd(a, b):
    """Extended Euclidian Algorithm."""

    # Explained here:
    # https://en.wikipedia.org/wiki/Extended_Euclidean_algorithm
    #
    if a == 0:
      return (b, 0, 1)
    else:
      g, y, x = egcd(b % a, a)
    return (g, x - (b // a) * y, y)

  # Modular inverse of x mod m is the number x^-1 such that
  #   x * x^-1 = 1 mod m
  #
  g, x, _ = egcd(a, m)
  if g != 1:
    raise Exception(f'modular inverse ({a}, {m}) does not exist')
  else:
    return x % m


def precompute_angles(a, n):
  """Pre-compute angles used in the Fourier Transform, for a."""

  # Convert 'a' to a string of 0's and 1's.
  s = bin(int(a))[2:].zfill(n)

  angles = [0.] * n
  for i in range(0, n):
    for j in range(i, n):
      if s[j] == '1':
        angles[n-i-1] += 2**(-(j-i))
    angles[n-i-1] *= math.pi
  return angles


def add(qc, q, a, n, factor):
  """Un-controlled add in fourier space."""

  angles = precompute_angles(a, n)
  for i in range(0, n):
    qc.u1(q[i], factor * angles[i])


def cadd(qc, q, ctl, a, n, factor):
  """Controlled add in fourier space."""

  angles = precompute_angles(a, n)
  for i in range(0, n):
    qc.cu1(ctl, q[i], factor * angles[i])


def ccphase(qc, angle, ctl1, ctl2, idx):
  """Controlled-controlled phase gate."""

  qc.cu1(ctl1, idx, angle/2)
  qc.cx(ctl2, ctl1)
  qc.cu1(ctl1, idx, -angle/2)
  qc.cx(ctl2, ctl1)
  qc.cu1(ctl2, idx, angle/2)


def ccadd(qc, q, ctl1, ctl2, a, n, factor):
  """Controlled-controlled add in fourier space."""

  angles = precompute_angles(a, n)
  for i in range(0, n):
    ccphase(qc, factor*angles[i], ctl1, ctl2, q[i])


def qft(qc, up_reg, n, with_swaps):
  """QFT."""

  for i in range(n-1, -1, -1):
    qc.h(up_reg[i])
    for j in range(i-1, -1, -1):
      qc.cu1(up_reg[i], up_reg[j], math.pi/2**(i-j))

  if with_swaps == 1:
    for i in range(n // 2):
      qc.swap(up_reg[i], up_reg[n-1-i])


def inverse_qft(qc, up_reg, n, with_swaps):
  """Inverse QFT."""

  if with_swaps == 1:
    for i in range(n // 2):
      qc.swap(up_reg[i], up_reg[n-1-i])

  for i in range(n):
    qc.h(up_reg[i])
    if i != n-1:
      j = i+1
      for y in range(i, -1, -1):
        qc.cu1(up_reg[j], up_reg[y], -math.pi / 2**(j-y))


def cc_add_mod_n(qc, q, ctl1, ctl2, aux, a, number, n):
  """Circuit that implements double controlled modular addition by a."""

  ccadd(qc, q, ctl1, ctl2, a, n, factor=1.0)
  add(qc, q, number, n, factor=-1.0)
  inverse_qft(qc, q, n, with_swaps=0)
  qc.cx(q[n-1], aux)
  qft(qc, q, n, with_swaps=0)
  cadd(qc, q, aux, number, n, factor=1.0)

  ccadd(qc, q, ctl1, ctl2, a, n, factor=-1.0)
  inverse_qft(qc, q, n, with_swaps=0)
  qc.x(q[n-1])
  qc.cx(q[n-1], aux)
  qc.x(q[n-1])
  qft(qc, q, n, with_swaps=0)
  ccadd(qc, q, ctl1, ctl2, a, n, factor=1.0)


def cc_add_mod_n_inverse(qc, q, ctl1, ctl2, aux, a, number, n):
  """Inverse of the double controlled modular addition."""

  ccadd(qc, q, ctl1, ctl2, a, n, factor=-1.0)
  inverse_qft(qc, q, n, with_swaps=0)
  qc.x(q[n-1])
  qc.cx(q[n-1], aux)
  qc.x(q[n-1])
  qft(qc, q, n, with_swaps=0)
  ccadd(qc, q, ctl1, ctl2, a, n, factor=1.0)

  cadd(qc, q, aux, number, n, factor=-1.0)
  inverse_qft(qc, q, n, with_swaps=0)
  qc.cx(q[n-1], aux)
  qft(qc, q, n, with_swaps=0)
  add(qc, q, number, n, factor=1.0)
  ccadd(qc, q, ctl1, ctl2, a, n, factor=-1.0)


def cmultmodn(qc, ctl, q, aux, a, number, n):
  """Controlled Multiplies modulo N."""

  print('Compute...')
  qft(qc, aux, n+1, with_swaps=0)
  for i in range(0, n):
    cc_add_mod_n(qc, aux, q[i], ctl, aux[n+1],
                 ((2**i)*a) % number, number, n+1)
  inverse_qft(qc, aux, n+1, with_swaps=0)

  print('Swap...')
  for i in range(0, n):
    qc.cswap(ctl, q[i], aux[i])
  a_inv = modular_inverse(a, number)

  print('Uncompute...')
  qft(qc, aux, n+1, with_swaps=0)
  for i in range(n-1, -1, -1):
    cc_add_mod_n_inverse(qc, aux, q[i], ctl, aux[n+1],
                         ((2**i)*a_inv) % number, number, n+1)
  inverse_qft(qc, aux, n+1, with_swaps=0)


def main(argv):
  if len(argv) > 1:
    raise app.UsageError('Too many command-line arguments.')
  print('Order Finding.')

  number = flags.FLAGS.N
  a = flags.FLAGS.a

  # The classical part are handled in 'shor_classic.py'
  nbits = number.bit_length()
  print('Shor: N = {}, a = {}, n = {} -> qubits: {}'
        .format(number, a, nbits, nbits*4 + 2))
  qc = circuit.qc('order_finding')

  # Aux register for additional and multiplication.
  aux = qc.reg(nbits+2, name='q0')

  # Register for QFT. This reg will hold the resulting x-value.
  up = qc.reg(nbits*2, name='q1')

  # Register for multiplications.
  down = qc.reg(nbits, name='q2')

  qc.h(up)
  qc.x(down[0])
  for i in range(0, nbits*2):
    cmultmodn(qc, up[i], down, aux, int(a**(2**i)), number, nbits)
  inverse_qft(qc, up, 2*nbits, with_swaps=1)

  qc.dump_to_file()

  # -- Results. An x-value of 128 would result in
  #    the correct continuous fractions.

  print('Measurement...')
  total_prob = 0.0
  for bits in helper.bitprod(nbits*4 + 2):
    prob = qc.psi.prob(*bits)
    if prob > 0.01:
      intval =  helper.bits2val(bits[nbits+2 : nbits+2 + nbits*2][::-1])
      phase = helper.bits2frac(
          bits[nbits+2 : nbits+2 + nbits*2][::-1], nbits*2)

      r = fractions.Fraction(phase).limit_denominator(8).denominator
      guesses = [math.gcd(a**(r//2)-1, number),
                 math.gcd(a**(r//2)+1, number)]

      print('Final x: {:3d} phase: {:3f} prob: {:.3f} factors: {}'.
            format(intval, phase, prob.real, guesses))

      total_prob += qc.psi.prob(*bits)
      if total_prob > 0.999:
        break

  print(qc.stats())


if __name__ == '__main__':
  app.run(main)
