import pickle
import os
import subprocess
from time import time
import numpy as np
from qcg.generators import gen_supremacy, gen_hwea
import MIQCP_searcher as searcher
import cutter
from helper_fun import evaluate_circ, cross_entropy, get_evaluator_info
import uniter_prob as uniter
from scipy.stats import wasserstein_distance
from qiskit import Aer, IBMQ, execute
from qiskit.providers.aer import noise
from qiskit.converters import circuit_to_dag, dag_to_circuit
import argparse

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='generate evaluator inputs')
    parser.add_argument('--min-qubit', metavar='N', type=int,help='Benchmark minimum number of HW qubits')
    parser.add_argument('--max-qubit', metavar='N', type=int,help='Benchmark maximum number of HW qubits')
    parser.add_argument('--max-clusters', metavar='N', type=int,help='max number of clusters to split into')
    parser.add_argument('--device-name', metavar='S',type=str,help='IBM device')
    args = parser.parse_args()

    device_name = args.device_name

    # NOTE: toggle circuits to benchmark
    dimension_l = [[2,2]]

    dirname = './benchmark_data'
    if not os.path.exists(dirname):
        os.mkdir(dirname)

    evaluator_input = {}
    
    for hw_max_qubit in range(args.min_qubit,args.max_qubit+1):
        for dimension in dimension_l:
            i,j = dimension
            if i*j<=hw_max_qubit:
                continue
            print('-'*100)
            
            # Generate a circuit
            print('%d * %d supremacy circuit'%(i,j))
            circ = gen_supremacy(i,j,8,order='75601234')
            # print('%d * %d HWEA circuit'%(i,j))
            # circ = gen_hwea(i*j,1)
            
            # Looking for a cut
            searcher_begin = time()
            hardness, positions, ancilla, d, num_cluster, m = searcher.find_cuts(circ,num_clusters=range(2,args.max_clusters+1),hw_max_qubit=hw_max_qubit,evaluator_weight=1)
            searcher_time = time() - searcher_begin
            if m == None:
                continue
            # m.print_stat()

            clusters, complete_path_map, K, d = cutter.cut_circuit(circ, positions)
            print('Complete path map:')
            [print(x,complete_path_map[x]) for x in complete_path_map]
            
            # Evaluate full circuit
            print('Evaluating sv noiseless fc')
            sv_noiseless_fc = evaluate_circ(circ=circ,backend='statevector_simulator',evaluator_info=None)
            identical_dist_ce = cross_entropy(target=sv_noiseless_fc,obs=sv_noiseless_fc)

            print('Evaluating qasm')
            evaluator_info = get_evaluator_info(circ=circ,device_name=device_name,fields=['num_shots'])
            print(evaluator_info.keys())
            qasm_noiseless_fc = evaluate_circ(circ=circ,backend='noiseless_qasm_simulator',evaluator_info=evaluator_info)
            print('Saturated  = %.3e shots'%evaluator_info['num_shots'])

            print('Evaluating qasm + noise')
            evaluator_info = get_evaluator_info(circ=circ,device_name=device_name,
            fields=['device','basis_gates','coupling_map','properties','initial_layout','noise_model','num_shots','meas_filter'])
            print(evaluator_info.keys())
            qasm_noisy_fc = evaluate_circ(circ=circ,backend='noisy_qasm_simulator',evaluator_info=evaluator_info)

    #         fc_evaluations = {'sv_noiseless':sv_noiseless_fc,
    #         'qasm':qasm_noiseless_fc,
    #         'qasm+noise':qasm_noisy_fc}

    #         evaluator_input[(hw_max_qubit,i*j)] = dimension,num_shots,searcher_time,circ,fc_evaluations,clusters,complete_path_map

    #         print('-'*100)
    # pickle.dump(evaluator_input,open('{}/evaluator_input.p'.format(dirname),'wb'))