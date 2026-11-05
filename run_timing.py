"""Monotonic mission milestones and elapsed time by operation, including failures."""
import time


class RunTiming:
    def __init__(self):
        self.started=time.monotonic();self.phases={};self.milestones={}
    def mark(self,name):
        self.milestones.setdefault(name,round(time.monotonic()-self.started,3))
    def call(self,name,function,*args,**kwargs):
        started=time.monotonic()
        try:return function(*args,**kwargs)
        finally:
            phase=self.phases.setdefault(name,{'seconds':0.,'calls':0})
            phase['seconds']+=time.monotonic()-started;phase['calls']+=1
    def summary(self):
        return {'total_elapsed_s':round(time.monotonic()-self.started,3),
                'milestones_s':dict(self.milestones),
                'phases':{name:{'seconds':round(value['seconds'],3),'calls':value['calls']}
                          for name,value in self.phases.items()}}
