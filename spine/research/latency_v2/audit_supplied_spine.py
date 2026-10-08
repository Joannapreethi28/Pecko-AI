"""Execute only inspected, dependency-free definitions from the supplied source.

No import/install of its NumPy/SciPy dependencies; no execution of nice_test.py.
Original files remain byte-identical in incoming_spine.
"""
import ast
from dataclasses import dataclass, field
import itertools
import json
import math
from pathlib import Path

root = Path(__file__).parent
source = (root/'incoming_spine'/'spine_core.py').read_text(encoding='utf-8')
names = {'Tier','Plan','amdahl','production_ratio','llm_decode_tps','predict_plan',
         'choose_plan','ControllerCfg','TierController'}
tree = ast.parse(source)
nodes = [n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
assert {n.name for n in nodes} == names
space = {'math':math,'itertools':itertools,'dataclass':dataclass,'field':field}
exec(compile(ast.Module(body=nodes,type_ignores=[]),'supplied_core_subset','exec'),space)
Tier = space['Tier']
a=Tier('asr','asr',.9,.1,t1=.1)
l=Tier('llm','llm',.9,.4,t1=.01,tok_rate_1=4,bw_cap=8)
t=Tier('tts','tts',.9,.1,t1=.1)
best,feasible=space['choose_plan']([a],[l],[t],cap_c=2,ram_gb=2,slo_p90=20,
                                  hangover=.4,rho_max=10,spec_options=(False,))
fastest=min(feasible,key=lambda p:p.pred_ttfa)
assert best.pred_ttfa > fastest.pred_ttfa

Cfg,Controller=space['ControllerCfg'],space['TierController']
c=Controller(3,Cfg(slo_p90=1),start=0)
c.on_turn(1.1,0,None)  # one old-regime miss
c.replan_on_cap_change(1,1)
old_history=list(c.hist)
c.on_turn(1.1,2,None)  # a single miss under the new regime causes another downgrade
assert old_history == [True] and c.level==2

q=0.1
p_two_of_three=3*q*q*(1-q)+q**3
event_prior=1/2.8
turn_weighted_prior=sum(math.exp(-.8)*.8**k/math.factorial(k)/(k+2) for k in range(30))
result={
  'scope':'Reproductions from exact inspected original definitions; synthetic inputs',
  'original_planner':{
    'chosen_predicted_latency_s':best.pred_ttfa,
    'minimum_feasible_predicted_latency_s':fastest.pred_ttfa,
    'chosen_threads':[best.c_llm,best.c_tts],
    'fastest_serial_threads':[fastest.c_llm,fastest.c_tts],
    'interpretation':'Original quality-then-CPU objective does not minimize latency. Thread sums above cap are valid only with its stated serial scheduling.',
  },
  'cap_replan_retains_old_violation_history':old_history,
  'level_after_one_new_regime_miss':c.level,
  'probability_two_misses_in_three_at_true_10pct_miss_rate':p_two_of_three,
  'at_least_one_two_of_three_alarm_in_25_independent_blocks':1-(1-p_two_of_three)**25,
  'endpoint_simulation_event_prior':event_prior,
  'endpoint_simulation_turn_weighted_prior_used':turn_weighted_prior,
  'original_verification_output':'Provided by other agent; full NumPy/SciPy scripts not rerun',
}
(root/'supplied_code_audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
