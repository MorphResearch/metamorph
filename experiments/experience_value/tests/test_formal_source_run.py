"""Offline acceptance for formal source block 01; never contacts a provider."""
from __future__ import annotations
import hashlib, json, shutil, tempfile, unittest
from pathlib import Path
from llm.adapters import AdapterResponse, ProviderAdapter
from experiments.experience_value.formal_source_run import execute
from experiments.experience_value.live import EXPERIENCE_GENERATION_PROMPT
from experiments.experience_value.tests.test_public_viability_gate_run import tool_call
from experiments.experience_value.workspace import WorkspaceAccessError, WorkspaceManager

ROOT=Path(__file__).resolve().parents[3]
PENDING=ROOT/'experiments/experience_value/formal_source_block_01.pending.json'
AUTH=ROOT/'experiments/experience_value/formal_source_block_01.authorization.pending.json'

class Fake(ProviderAdapter):
    def __init__(self): self.steps={}; self.requests=[]
    def stream(self, **_): raise TypeError()
    def complete_configured(self, *, model_name, messages, tools, generation_options):
        task=next(m['content'] for m in messages if 'Task ID:' in m.get('content','')).split('Task ID: ')[1].split('\n')[0]
        self.requests.append((task,tools,messages[-1].get('content')))
        if messages[-1].get('content')==EXPERIENCE_GENERATION_PROMPT:
            return AdapterResponse(content=f'formal experience {task}',usage={'prompt_tokens':20,'completion_tokens':4},stop_reason='stop')
        n=self.steps.get(task,0); self.steps[task]=n+1
        if n<15: return AdapterResponse(tool_calls=[tool_call(f'{task}-{n}','query_sql',{'sql':'.tables'})],usage={'prompt_tokens':20,'completion_tokens':4},stop_reason='tool_calls')
        return AdapterResponse(content='0',usage={'prompt_tokens':20,'completion_tokens':1},stop_reason='stop')

class FormalSourceTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); self.p=self.root/'p.json'; self.a=self.root/'a.json'; shutil.copy(PENDING,self.p); shutil.copy(AUTH,self.a)
 def tearDown(self): self.t.cleanup()
 def test_block_is_exact_and_fake_path_commits(self):
  report=json.loads(execute(pending_path=self.p,authorization_path=self.a,output_root=self.root/'out',mode='fake',adapter=Fake()).read_text())
  self.assertEqual([(x['manifest_position'],x['task_id'],x['condition']) for x in report['episodes']],[(1,'7','F0'),(2,'7','U0'),(3,'7','F1'),(4,'7','U1')])
  self.assertEqual(report['status'],'COMPLETED')
  self.assertTrue(all(x['artifact_provenance'] and x['artifact_provenance'][0]['raw_visible_content_sha256']==x['artifact_provenance'][0]['committed_file_sha256'] for x in report['episodes']))
  self.assertEqual(report['next_manifest_position'],5)
 def test_unsigned_live_rejects_before_provider(self):
  with self.assertRaises(Exception): execute(pending_path=self.p,authorization_path=self.a,output_root=self.root/'live',mode='live',adapter=Fake())
 def test_inherited_formal_memory_is_immutable_and_controls_empty(self):
  w=WorkspaceManager(self.root/'w'); f1=w.start_task(condition='F1',replicate='formal',task_id='7'); w.write_agent_file(f1,'/memory/experience_001.md',b'x'); snap=w.freeze_memory(f1); f1next=w.start_task(condition='F1',replicate='formal',task_id='8',parent=snap)
  self.assertEqual(w.read_agent_file(f1next,'/memory/experience_001.md'),b'x')
  with self.assertRaises(WorkspaceAccessError): w.write_agent_file(f1next,'/memory/experience_001.md',b'y')
  self.assertFalse((w.start_task(condition='F0',replicate='formal',task_id='8').memory_root/'experience_001.md').exists())
