from .supremacy import Qgrid
from .supremacy import Qbit
#from .ansatz import HWEA
from .QAOA import hw_efficient_ansatz

def gen_supremacy(height, width, depth, order=None, singlegates=True, mirror=True):
    """
    Calling this function will create and return a quantum supremacy
    circuit as found in https://www.nature.com/articles/s41567-018-0124-x
    """

    grid = Qgrid.Qgrid(height, width, depth, order=order, singlegates=singlegates, mirror=mirror)

    circ = grid.gen_circuit(barriers=False)

    return circ


def gen_hwea(width, depth):
    """
    Create a quantum circuit implementing a hardware efficient
    ansatz with the given width (number of qubits) and 
    depth (number of repetitions of the basic ansatz).
    """

    hwea = hw_efficient_ansatz.HWEA(width, depth)

    circ = hwea.gen_circuit()

    return circ