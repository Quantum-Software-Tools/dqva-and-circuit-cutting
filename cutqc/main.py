import os, subprocess, pickle, glob, random, time
from termcolor import colored
import numpy as np
import multiprocessing as mp

from qiskit_helper_functions.non_ibmq_functions import evaluate_circ, read_dict, find_process_jobs

from cutqc.helper_fun import check_valid, get_dirname
from cutqc.cutter import find_cuts
from cutqc.evaluator import find_subcircuit_O_rho_qubits, find_all_combinations, get_subcircuit_instance, sv_simulate, runtime_simulate
from cutqc.post_process import get_combinations, build

class CutQC:
    def __init__(self, circuits):
        self.circuits = circuits
        self.check_input()

    def check_input(self):
        for circuit_name in self.circuits:
            circuit = self.circuits[circuit_name]
            valid = check_valid(circuit=circuit)
            assert valid
    
    def cut(self, max_subcircuit_qubit, num_subcircuits, max_cuts):
        for circuit_name in self.circuits:
            circuit = self.circuits[circuit_name]
            cut_solution = find_cuts(circuit=circuit,
            max_subcircuit_qubit=max_subcircuit_qubit,
            num_subcircuits=num_subcircuits,
            max_cuts=max_cuts,verbose=True)
            self.circuits[circuit_name] = cut_solution
            dirname = get_dirname(circuit_name=circuit_name,max_subcircuit_qubit=max_subcircuit_qubit,
            early_termination=None,eval_mode=None,num_workers=None,qubit_limit=None,field='cutter')
            if os.path.exists(dirname):
                subprocess.run(['rm','-r',dirname])
            os.makedirs(dirname)
            pickle.dump(cut_solution, open('%s/subcircuits.pckl'%(dirname),'wb'))
    
    def evaluate(self,circuit_cases,eval_mode,num_workers,early_termination):
        self._run_subcircuits(circuit_cases=circuit_cases,eval_mode=eval_mode,num_workers=num_workers)
        # self._measure(eval_mode=eval_mode)
        # self._organize(num_workers=num_workers,eval_mode=eval_mode)
        # if 0 in early_termination:
        #     self._vertical_collapse(early_termination=0,eval_mode=eval_mode)
        # if 1 in early_termination:
        #     self._vertical_collapse(early_termination=1,eval_mode=eval_mode)
    
    def post_process(self,num_workers,eval_mode,early_termination,qubit_limit,recursion_depth):
        subprocess.run(['rm','./cutqc/merge'])
        subprocess.run(['icc','-mkl','./cutqc/merge.c','-o','./cutqc/merge','-lm'])
        subprocess.run(['rm','./cutqc/build'])
        subprocess.run(['icc','-fopenmp','-mkl','-lpthread','-march=native','./cutqc/build.c','-o','./cutqc/build','-lm'])

        for circuit_name in self.circuits:
            full_circuit = self.circuits[circuit_name]['circuit']
            max_subcircuit_qubit = self.circuits[circuit_name]['max_subcircuit_qubit']
            subcircuits = self.circuits[circuit_name]['subcircuits']
            complete_path_map = self.circuits[circuit_name]['complete_path_map']
            counter = self.circuits[circuit_name]['counter']

            print('-'*10,'%d-qubit %s on %d-q NISQ'%(full_circuit.num_qubits,circuit_name,max_subcircuit_qubit),'-'*10,flush=True)

            dest_folder = get_dirname(circuit_name=circuit_name,max_subcircuit_qubit=max_subcircuit_qubit,
            early_termination=early_termination,num_workers=num_workers,eval_mode=eval_mode,qubit_limit=qubit_limit,field='build')

            if os.path.exists('%s'%dest_folder):
                subprocess.run(['rm','-r',dest_folder])
            os.makedirs(dest_folder)

            vertical_collapse_folder = get_dirname(circuit_name=circuit_name,max_subcircuit_qubit=max_subcircuit_qubit,
            early_termination=early_termination,num_workers=None,eval_mode=eval_mode,qubit_limit=None,field='vertical_collapse')

            for recursion_layer in range(recursion_depth):
                print('--> Recursion layer %d <--'%(recursion_layer),flush=True)
                print('__Distribute Workload__',flush=True)
                # NOTE: hardcode recursion_qubit here for ASPLOS rebuttal experiment
                recursion_qubit = [1,10,10][recursion_layer]
                subprocess.run(args=['python', '-m','cutqc.distributor',
                '--circuit_name',circuit_name,'--max_subcircuit_qubit',str(max_subcircuit_qubit),'--early_termination',str(early_termination),
                '--recursion_layer',str(recursion_layer),'--qubit_limit',str(qubit_limit),'--recursion_qubit',str(recursion_qubit),
                '--num_workers',str(num_workers),'--eval_mode',eval_mode])
                print('__Merge__',flush=True)
                terminated = self._merge(full_circuit=full_circuit,circuit_name=circuit_name,
                max_subcircuit_qubit=max_subcircuit_qubit,
                vertical_collapse_folder=vertical_collapse_folder,dest_folder=dest_folder,
                recursion_layer=recursion_layer)
                if terminated:
                    break
                print('__Build__',flush=True)
                reconstructed_prob = self._build(full_circuit=full_circuit,circuit_name=circuit_name,max_subcircuit_qubit=max_subcircuit_qubit,
                dest_folder=dest_folder,recursion_layer=recursion_layer)
    
    def verify(self,circuit_name, max_subcircuit_qubit, early_termination, num_workers, qubit_limit, eval_mode):
        subprocess.run(['python','-m','cutqc.verify',
        '--circuit_name',circuit_name,
        '--max_subcircuit_qubit',str(max_subcircuit_qubit),
        '--early_termination',str(early_termination),
        '--num_workers',str(num_workers),
        '--qubit_limit',str(qubit_limit),
        '--eval_mode',eval_mode])
    
    def _run_subcircuits(self,circuit_cases,eval_mode,num_workers):
        for circuit_case in circuit_cases:
            circuit_name = circuit_case['name']
            max_subcircuit_qubit = circuit_case['max_subcircuit_qubit']
            dirname = get_dirname(circuit_name=circuit_name,max_subcircuit_qubit=max_subcircuit_qubit,
            early_termination=None,eval_mode=None,num_workers=None,qubit_limit=None,field='cutter')
            cut_solution = read_dict('%s/subcircuits.pckl'%(dirname))
            max_subcircuit_qubit = cut_solution['max_subcircuit_qubit']
            subcircuits = cut_solution['subcircuits']
            complete_path_map = cut_solution['complete_path_map']
            counter = cut_solution['counter']

            eval_folder = get_dirname(circuit_name=circuit_name,max_subcircuit_qubit=max_subcircuit_qubit,
            early_termination=None,num_workers=None,eval_mode=eval_mode,qubit_limit=None,field='evaluator')
            if os.path.exists(eval_folder):
                subprocess.run(['rm','-r',eval_folder])
            os.makedirs(eval_folder)

            circ_dict = {}
            all_indexed_combinations = {}
            for subcircuit_idx, subcircuit in enumerate(subcircuits):
                O_qubits, rho_qubits = find_subcircuit_O_rho_qubits(complete_path_map=complete_path_map,subcircuit_idx=subcircuit_idx)
                combinations, indexed_combinations = find_all_combinations(O_qubits, rho_qubits, subcircuit.qubits)
                circ_dict.update(get_subcircuit_instance(subcircuit_idx=subcircuit_idx,subcircuit=subcircuit, combinations=combinations))
                all_indexed_combinations[subcircuit_idx] = indexed_combinations
            pickle.dump(all_indexed_combinations, open('%s/all_indexed_combinations.pckl'%(eval_folder),'wb'))

            data = []
            for key in circ_dict:
                data.append([key,circ_dict[key]['circuit'],eval_folder,counter])
            random.shuffle(data) # Ensure a somewhat fair distribution of workloads
            chunksize = max(len(data)//num_workers//10,1)
            
            pool = mp.Pool(processes=num_workers)
            if eval_mode=='sv':
                pool.starmap(sv_simulate,data,chunksize=chunksize)
            elif eval_mode=='runtime':
                pool.starmap(runtime_simulate,data,chunksize=chunksize)
    
    def _measure(self, eval_mode):
        subprocess.run(['rm','./cutqc/measure'])
        subprocess.run(['icc','./cutqc/measure.c','-o','./cutqc/measure','-lm'])

        for circuit_name in self.circuits:
            full_circuit = self.circuits[circuit_name]['circuit']
            subcircuits = self.circuits[circuit_name]['subcircuits']
            max_subcircuit_qubit = self.circuits[circuit_name]['max_subcircuit_qubit']

            eval_folder = get_dirname(circuit_name=circuit_name,max_subcircuit_qubit=max_subcircuit_qubit,
            early_termination=None,num_workers=None,eval_mode=eval_mode,qubit_limit=None,field='evaluator')
            for subcircuit_idx in range(len(subcircuits)):
                eval_files = glob.glob('%s/raw_%d_*.txt'%(eval_folder,subcircuit_idx))
                eval_files = [str(x) for x in range(len(eval_files))]
                rank = 0
                subprocess.run(args=['./cutqc/measure', '%d'%rank, eval_folder,
                '%d'%full_circuit.num_qubits,'%d'%subcircuit_idx, '%d'%len(eval_files), *eval_files])
    
    def _organize(self, num_workers, eval_mode):
        '''
        Organize parallel processing for the subsequent vertical collapse procedure
        '''
        for circuit_name in self.circuits:
            full_circuit = self.circuits[circuit_name]['circuit']
            max_subcircuit_qubit = self.circuits[circuit_name]['max_subcircuit_qubit']
            subcircuits = self.circuits[circuit_name]['subcircuits']
            complete_path_map = self.circuits[circuit_name]['complete_path_map']
            counter = self.circuits[circuit_name]['counter']

            eval_folder = get_dirname(circuit_name=circuit_name,max_subcircuit_qubit=max_subcircuit_qubit,
            early_termination=None,num_workers=None,eval_mode=eval_mode,qubit_limit=None,field='evaluator')

            all_indexed_combinations = read_dict(filename='%s/all_indexed_combinations.pckl'%(eval_folder))
            O_rho_pairs, combinations = get_combinations(complete_path_map=complete_path_map)
            kronecker_terms, _ = build(full_circuit=full_circuit, combinations=combinations,
            O_rho_pairs=O_rho_pairs, subcircuits=subcircuits, all_indexed_combinations=all_indexed_combinations)

            for rank in range(num_workers):
                subcircuit_kron_terms_file = open('%s/subcircuit_kron_terms_%d.txt'%(eval_folder,rank),'w')
                subcircuit_kron_terms_file.write('%d subcircuits\n'%len(kronecker_terms))
                for subcircuit_idx in kronecker_terms:
                    rank_subcircuit_kron_terms = find_process_jobs(jobs=list(kronecker_terms[subcircuit_idx].keys()),rank=rank,num_workers=num_workers)
                    subcircuit_kron_terms_file.write('subcircuit %d kron_terms %d num_effective %d\n'%(
                        subcircuit_idx,len(rank_subcircuit_kron_terms),counter[subcircuit_idx]['effective']))
                    for subcircuit_kron_term in rank_subcircuit_kron_terms:
                        subcircuit_kron_terms_file.write('subcircuit_kron_index=%d kron_term_len=%d\n'%(kronecker_terms[subcircuit_idx][subcircuit_kron_term],len(subcircuit_kron_term)))
                        [subcircuit_kron_terms_file.write('%d,%d '%(x[0],x[1])) for x in subcircuit_kron_term]
                        subcircuit_kron_terms_file.write('\n')
                    if rank==0:
                        print('Rank %d needs to vertical collapse %d/%d instances of subcircuit %d'%(rank,len(rank_subcircuit_kron_terms),len(kronecker_terms[subcircuit_idx]),subcircuit_idx),flush=True)
                subcircuit_kron_terms_file.close()
    
    def _vertical_collapse(self,early_termination,eval_mode):
        subprocess.run(['rm','./cutqc/vertical_collapse'])
        subprocess.run(['icc','-mkl','./cutqc/vertical_collapse.c','-o','./cutqc/vertical_collapse','-lm'])

        for circuit_name in self.circuits:
            full_circuit = self.circuits[circuit_name]['circuit']
            max_subcircuit_qubit = self.circuits[circuit_name]['max_subcircuit_qubit']
            subcircuits = self.circuits[circuit_name]['subcircuits']
            complete_path_map = self.circuits[circuit_name]['complete_path_map']
            counter = self.circuits[circuit_name]['counter']

            eval_folder = get_dirname(circuit_name=circuit_name,max_subcircuit_qubit=max_subcircuit_qubit,
            early_termination=None,num_workers=None,eval_mode=eval_mode,qubit_limit=None,field='evaluator')
            vertical_collapse_folder = get_dirname(circuit_name=circuit_name,max_subcircuit_qubit=max_subcircuit_qubit,
            early_termination=early_termination,num_workers=None,eval_mode=eval_mode,qubit_limit=None,field='vertical_collapse')

            rank_files = glob.glob('%s/subcircuit_kron_terms_*.txt'%eval_folder)
            if len(rank_files)==0:
                raise Exception('There are no rank_files for _vertical_collapse')
            if os.path.exists(vertical_collapse_folder):
                subprocess.run(['rm','-r',vertical_collapse_folder])
            os.makedirs(vertical_collapse_folder)
            child_processes = []
            for rank in range(len(rank_files)):
                subcircuit_kron_terms_file = '%s/subcircuit_kron_terms_%d.txt'%(eval_folder,rank)
                p = subprocess.Popen(args=['./cutqc/vertical_collapse', '%d'%full_circuit.num_qubits, '%s'%subcircuit_kron_terms_file, '%s'%eval_folder, '%s'%vertical_collapse_folder, '%d'%early_termination, '%d'%rank])
                child_processes.append(p)
            for rank in range(len(rank_files)):
                cp = child_processes[rank]
                cp.wait()
                if early_termination==1:
                    subprocess.run(['rm','%s/subcircuit_kron_terms_%d.txt'%(eval_folder,rank)])
            if early_termination==1:
                measured_files = glob.glob('%s/measured*.txt'%eval_folder)
                for measured_file in measured_files:
                    subprocess.run(['rm',measured_file])
    
    def _merge(self, full_circuit, circuit_name, max_subcircuit_qubit, dest_folder, recursion_layer, vertical_collapse_folder):
        dynamic_definition_folder = '%s/dynamic_definition_%d'%(dest_folder,recursion_layer)
        if not os.path.exists(dynamic_definition_folder):
            return True
        merge_files = glob.glob('%s/merge_*.txt'%dynamic_definition_folder)
        num_workers = len(merge_files)
        child_processes = []
        for rank in range(num_workers):
            merge_file = '%s/merge_%d.txt'%(dynamic_definition_folder,rank)
            p = subprocess.Popen(args=['./cutqc/merge', '%s'%merge_file, '%s'%vertical_collapse_folder, '%s'%dynamic_definition_folder,
            '%d'%rank, '%d'%recursion_layer])
            child_processes.append(p)
        elapsed = 0
        for rank in range(num_workers):
            cp = child_processes[rank]
            cp.wait()
        time.sleep(1)
        rank_logs = open('%s/rank_%d_summary.txt'%(dynamic_definition_folder,rank), 'r')
        lines = rank_logs.readlines()
        assert lines[-2].split(' = ')[0]=='Total merge time' and lines[-1]=='DONE'
        elapsed = max(elapsed,float(lines[-2].split(' = ')[1]))

        time_str = colored('%d-q %s on %d-q NISQ took %.3e seconds'%(full_circuit.num_qubits,circuit_name,max_subcircuit_qubit,elapsed),'blue')
        print(time_str,flush=True)
        pickle.dump({'merge_time_%d'%recursion_layer:elapsed}, open('%s/summary.pckl'%(dest_folder),'ab'))
        return False
    
    def _build(self, full_circuit, circuit_name, max_subcircuit_qubit, dest_folder, recursion_layer):
        dynamic_definition_folder = '%s/dynamic_definition_%d'%(dest_folder,recursion_layer)
        build_files = glob.glob('%s/build_*.txt'%dynamic_definition_folder)
        num_workers = len(build_files)
        child_processes = []
        for rank in range(num_workers):
            build_file = '%s/build_%d.txt'%(dynamic_definition_folder,rank)
            p = subprocess.Popen(args=['./cutqc/build', '%s'%build_file, '%s'%dynamic_definition_folder, 
            '%s'%dynamic_definition_folder, '%d'%rank, '%d'%recursion_layer])
            child_processes.append(p)
        
        elapsed = []
        reconstructed_prob = None
        for rank in range(num_workers):
            cp = child_processes[rank]
            cp.wait()
            rank_logs = open('%s/rank_%d_summary.txt'%(dynamic_definition_folder,rank), 'r')
            lines = rank_logs.readlines()
            assert lines[-2].split(' = ')[0]=='Total build time' and lines[-1] == 'DONE'
            elapsed.append(float(lines[-2].split(' = ')[1]))

            fp = open('%s/reconstructed_prob_%d.txt'%(dynamic_definition_folder,rank), 'r')
            for i, line in enumerate(fp):
                rank_reconstructed_prob = line.split(' ')[:-1]
                rank_reconstructed_prob = np.array(rank_reconstructed_prob)
                rank_reconstructed_prob = rank_reconstructed_prob.astype(np.float)
                if i>0:
                    raise Exception('C build_output should not have more than 1 line')
            fp.close()
            subprocess.run(['rm','%s/reconstructed_prob_%d.txt'%(dynamic_definition_folder,rank)])
            if isinstance(reconstructed_prob,np.ndarray):
                reconstructed_prob += rank_reconstructed_prob
            else:
                reconstructed_prob = rank_reconstructed_prob
        time_str = colored('%d-q %s on %d-q cc_size took %.3e seconds'%(full_circuit.num_qubits,circuit_name,max_subcircuit_qubit,max(elapsed)),'blue')
        print(time_str,flush=True)
        pickle.dump({'build_time_%d'%recursion_layer:np.array(elapsed)}, open('%s/summary.pckl'%(dest_folder),'ab'))
        max_states = sorted(range(len(reconstructed_prob)),key=lambda x:reconstructed_prob[x],reverse=True)
        pickle.dump({'zoomed_ctr':0,'max_states':max_states,'reconstructed_prob':reconstructed_prob},open('%s/build_output.pckl'%(dynamic_definition_folder),'wb'))
        return reconstructed_prob