"""Bounded RTL evidence used by the capacity search, without the N=180 matrix."""


def capacity_cases(capacity):
    if not 2 <= capacity <= 20:
        raise ValueError('Capacity validation requires 2..20 modules per board')
    prefix = f'tb_ptp_capacity_k{capacity}'
    nodes = 3 * capacity
    samples = f'G_NODES=>{nodes},G_NOMINAL_SAMPLES=>32,G_SAMPLE_SPACING=>997,G_CAPACITY_CSV=>true'
    return {
        prefix+'_runtime': dict(entity='tb_ptp_runtime_chain', generics=(
            f'G_CAPACITY=>{capacity},G_INITIAL_NODES=>{nodes},G_REDUCED_NODES=>{nodes-2},G_PHASED=>true')),
        prefix: dict(entity='tb_ptp_chain', generics=samples),
        prefix+'_uneven': dict(entity='tb_ptp_chain', generics=(
            f'G_NODES=>{nodes-1},G_NOMINAL_SAMPLES=>32,G_SAMPLE_SPACING=>997,G_CAPACITY_CSV=>true')),
        prefix+'_jitter': dict(entity='tb_ptp_chain', generics=samples+
            ',G_PHASED=>true,G_DRIFT=>2000,G_JITTER_MASK=>3,G_SEED=>12345'),
        prefix+'_asymmetry': dict(entity='tb_ptp_chain', generics=samples+
            ',G_PHASED=>true,G_ASYMMETRY=>true'),
        prefix+'_runtime_minimum': dict(entity='tb_ptp_runtime_chain', generics=(
            f'G_CAPACITY=>{capacity},G_INITIAL_NODES=>{nodes},G_REDUCED_NODES=>3,G_PHASED=>true')),
    }
