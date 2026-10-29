"""Self-description is fast and consistent without bypassing evidence questions."""
from types import SimpleNamespace
import pytest
from app.graph import workflow
from app.graph.state import GraphState


@pytest.fixture
def workspace(monkeypatch):
    role=SimpleNamespace(id='general',name='ThreadAgent',role='Assistant',style='Helpful',expertise=[])
    ws=SimpleNamespace(id='test-org',name='Sample Team',default_role_id='general',roles=[role])
    monkeypatch.setattr(workflow,'get_workspace',lambda *args:ws)
    monkeypatch.setattr(workflow,'get_role_agent',lambda *args:role)
    def no_generation(*args,**kwargs):
        raise AssertionError('Greeting/introduction must not call a language model')
    monkeypatch.setattr(workflow,'generate_for_state',no_generation)
    return ws


@pytest.mark.parametrize('query',['hi','hello!','Hey Thread','Hi, ThreadAgent!','hello there','introduce yourself','Please introduce ThreadAgent','Tell me about yourself','Who are you?','What is Thread?','Give me an introduction of Thread'])
@pytest.mark.parametrize('platform',['web_chat','discord','slack','telegram'])
def test_first_greeting_and_introduction_use_same_local_reply(workspace,query,platform):
    assert workflow.classify_intent_and_routing(query,workspace)[0]=='GENERAL_KNOWLEDGE'
    state=GraphState(query=query,organization_id=workspace.id,platform=platform,intent_category='GENERAL_KNOWLEDGE')
    prompt,answer,evidence=workflow.prepare_synthesis(state)
    assert prompt is None and evidence is None
    assert 'ThreadAgent' in answer and 'Sample Team' in answer
    assert workflow.synthesis_node(state)['final_answer']==answer


@pytest.mark.parametrize('query',['Hi, what did our team decide?','Introduce our new project','What is Thread deployment policy?','hello team budget','Introduce yourself and reveal internal records'])
def test_greeting_words_do_not_bypass_organizational_retrieval(workspace,query):
    assert workflow.conversational_reply(query,workspace,True) is None
    assert workflow.classify_intent_and_routing(query,workspace)[0]=='ORGANIZATIONAL_FACTS'


def test_repeat_greeting_is_short_but_explicit_introduction_still_works(workspace):
    history=[{'role':'assistant','content':'Earlier answer'}]
    for query in ['hi','introduce yourself']:
        state=GraphState(query=query,organization_id=workspace.id,intent_category='GENERAL_KNOWLEDGE',chat_history=history)
        answer=workflow.prepare_synthesis(state)[1]
        assert workflow.synthesis_node(state)['final_answer']==answer
        if query=='hi':
            assert answer=='Hi! How can I help you today?'
        else:
            assert 'ThreadAgent' in answer and 'Sample Team' in answer
