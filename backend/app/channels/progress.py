"""Short factual status messages, scoped to a native request and its destination."""
from contextvars import ContextVar
import logging
import os
import re
from time import monotonic
import uuid

logger=logging.getLogger(__name__)
_sink=ContextVar('native_progress_sink',default=None)


def initial_message(query):
    lower=query.lower()
    if re.search(r'!github|\b(github|repository|repo|commits?|pull requests?)\b',lower):
        return 'Checking repository activity…'
    if re.search(r'!events|\b(upcoming events|workshops)\b',lower):
        return 'Checking upcoming events…'
    if re.search(r'!faq|!resources',lower):
        return 'Checking workspace resources…'
    if re.search(r'^(hi|hey|hello|who are you|tell me about yourself|(?:please )?introduce)\b',lower):
        return 'Preparing a reply…'
    if re.search(r'\b(explain|mutex|semaphore|programming|algorithm)\b',lower):
        return 'Preparing an answer…'
    return 'Checking records…'


def notify_stage(stage,state):
    sink=_sink.get()
    if sink is not None:
        sink(stage,state)


class NativeProgress:
    def __init__(self,principal,platform,destination,query,idempotency_key=None):
        self.principal=principal;self.platform=platform;self.destination=destination
        self.enabled=(platform.value in {'discord','telegram','slack'} and os.getenv('THREAD_PROGRESS_ENABLED','true').lower() not in {'false','0','no'})
        self.initial=initial_message(query)
        self.key=idempotency_key or 'progress_'+uuid.uuid4().hex
        self.sent=[];self.token=None;self.started=monotonic();self.available=True

    def _send(self,text):
        if not self.enabled or not self.available or text in self.sent:
            return
        from app.channels.outbound import channel_message_delivery_service
        try:
            channel_message_delivery_service.send_prepared_message(
                principal=self.principal,platform=self.platform,destination_id=self.destination,
                text=text,citations=[],receipt=None,
                idempotency_key=f'{self.key}:progress:{len(self.sent)}',
            )
            self.sent.append(text)
        except PermissionError:
            raise  # Never bypass a rejected destination to display progress.
        except Exception as exc:
            self.available=False
            logger.warning('Progress delivery unavailable (%s); continuing the query.',type(exc).__name__)

    def __enter__(self):
        if self.enabled:
            self._send(self.initial)
            self.token=_sink.set(self.stage)
        return self

    def stage(self,name,state):
        # At most two progress posts, and only real execution milestones.
        if len(self.sent)>=2 or monotonic()-self.started<1.5:
            return
        if name=='synthesis':
            if state.intent_category=='TOOL_EXECUTION':
                labels={'github':'Checking repository activity…','events':'Checking upcoming events…','resources':'Checking workspace resources…','summary':'Summarizing the available records…'}
                self._send(labels.get(state.tool_name,'Running the requested tool…'))
            elif state.intent_category=='ORGANIZATIONAL_FACTS':
                self._send('Preparing the answer from the available records…')

    def __exit__(self,*args):
        if self.token is not None:_sink.reset(self.token)
