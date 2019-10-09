import pickle
from time import time
from qcg.generators import gen_supremacy, gen_hwea
import MIQCP_searcher as searcher
import cutter
import evaluator_prob as evaluator
import uniter_prob as uniter
from scipy.stats import wasserstein_distance
from qiskit import Aer, IBMQ, execute
from qiskit.providers.aer import noise

provider = IBMQ.load_account()
device = provider.get_backend('ibmq_16_melbourne')
properties = device.properties()
coupling_map = device.configuration().coupling_map

gate_times = [
('u1', None, 0), ('u2', None, 100), ('u3', None, 200),
('cx', [1, 0], 678), ('cx', [1, 2], 547), ('cx', [2, 3], 721),
('cx', [4, 3], 733), ('cx', [4, 10], 721), ('cx', [5, 4], 800),
('cx', [5, 6], 800), ('cx', [5, 9], 895), ('cx', [6, 8], 895),
('cx', [7, 8], 640), ('cx', [9, 8], 895), ('cx', [9, 10], 800),
('cx', [11, 10], 721), ('cx', [11, 3], 634), ('cx', [12, 2], 773),
('cx', [13, 1], 2286), ('cx', [13, 12], 1504), ('cx', [], 800)]

noise_model = noise.device.basic_device_noise_model(properties, gate_times=gate_times)
basis_gates = noise_model.basis_gates
provider_info=(provider,noise_model,coupling_map,basis_gates)

times = {'searcher':[],'evaluator':[],'uniter':[]}
num_qubits = []
noiseless_reconstruction_distance = []
noisy_reconstruction_distance = []
max_qubit = 12

for dimension in [[4,5]]:
    i,j = dimension
    if i*j<=24 and i*j not in num_qubits:
        print('-'*200)
        print('%d * %d supremacy circuit'%(i,j))

        # Generate a circuit
        circ = gen_supremacy(i,j,8,order='75601234')
        # print(circ)

        # Looking for a cut
        searcher_begin = time()
        hardness, positions, ancilla, d, num_cluster, m = searcher.find_cuts(circ,num_clusters=range(1,5),hw_max_qubit=max_qubit,alpha=0)
        searcher_time = time() - searcher_begin
        m.print_stat()

        if len(positions)>0:

            # Simulate the clusters
            evaluator_begin = time()
            all_cluster_prob = evaluator.simulate_clusters(complete_path_map=complete_path_map,
            clusters=clusters,
            provider_info=provider_info,
            simulator_backend='statevector_simulator',noisy=False)
            evaluator_end = time()

            # Simulate the clusters
            evaluator_begin = time()
            all_cluster_prob = evaluator.evaluate_clusters(complete_path_map=complete_path_map,
            clusters=clusters,
            provider_info=provider_info,
            simulator_backend='ibmq_qasm_simulator',noisy=True)
            evaluator_time = time()-evaluator_begin

            # Reconstruct the circuit
            uniter_begin = time()
            reconstructed_prob = uniter.reconstruct(complete_path_map, circ, clusters, all_cluster_prob)
            uniter_time = time()-uniter_begin
        
        else:
            reconstructed_prob = evaluator.simulate_circ(circ=circ, simulator='ibmq_qasm_simulator', noisy=True, provider_info=provider_info, output_format='prob',num_shots=1024)
            evaluator_time = 0
            uniter_time = 0

        full_circ_noiseless_prob = evaluator.simulate_circ(circ=circ,simulator='statevector_simulator',output_format='prob')
        noiseless_distance = wasserstein_distance(full_circ_noiseless_prob,reconstructed_prob)
        full_circ_noisy_prob = evaluator.simulate_circ(circ=circ, simulator='ibmq_qasm_simulator', noisy=True, provider_info=provider_info, output_format='prob', num_shots=1024)
        noisy_distance = wasserstein_distance(full_circ_noisy_prob,reconstructed_prob)
        
        noiseless_reconstruction_distance.append(noiseless_distance)
        noisy_reconstruction_distance.append(noisy_distance)
        times['searcher'].append(searcher_time)
        times['evaluator'].append(evaluator_time)
        times['uniter'].append(uniter_time)
        num_qubits.append(i*j)
        print('probability reconstruction distance to noiseless full circ = ',noiseless_distance)
        print('probability reconstruction distance to noisy full circ = ',noisy_distance)
        # print('searcher time = %.3f seconds'%(searcher_end-searcher_begin))
        print('evaluator time = %.3f seconds'%evaluator_time)
        print('uniter time = %.3f seconds'%uniter_time)
        print('-'*200)
print('*'*200)
print(times)
print('num qubits:',num_qubits)
print('noiseless reconstruction distance:',noiseless_reconstruction_distance)

pickle.dump([num_qubits,times,noiseless_reconstruction_distance,noisy_reconstruction_distance], open( 'full_stack_benchmark.p','wb'))