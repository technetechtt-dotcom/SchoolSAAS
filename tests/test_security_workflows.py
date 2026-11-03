"""Regression tests for new multi-school access and review flows."""
import os
os.environ.setdefault('JWT_SECRET','unit-test-only-secret-not-for-deployment')
os.environ['DATABASE_URL']='sqlite://'
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app import main

def test_invitation_csrf_scope_and_review():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    Session=sessionmaker(engine,expire_on_commit=False)
    def db():
        with Session() as s:
            yield s
    main.app.dependency_overrides[main.db]=db
    try:
        admin=TestClient(main.app)
        def write(client,path,payload,method='post'):
            token=client.cookies.get('csrf_token','')
            return getattr(client,method)(path,json=payload,headers={'X-CSRF-Token':token})
        assert write(admin,'/api/register',{'school_name':'Test School','slug':'testschool','email':'admin@test.invalid','password':'long-test-password-123'}).status_code==201
        data={'admission_no':'001','first_name':'Demo','surname':'Learner','grade':'4','class_name':'4A'}
        assert admin.post('/api/learners',json=data).status_code==403
        assert write(admin,'/api/learners',data).status_code==201
        second=dict(data,admission_no='002',class_name='5B')
        assert write(admin,'/api/learners',second).status_code==201
        invite=write(admin,'/api/invitations',{'email':'teacher@test.invalid','role':'educator','assigned_class':'4A'})
        assert invite.status_code==201
        token=invite.json()['token']
        teacher=TestClient(main.app)
        assert write(teacher,'/api/invitations/accept',{'token':token,'password':'long-teacher-password-123'}).status_code==201
        assert write(teacher,'/api/invitations/accept',{'token':token,'password':'long-teacher-password-123'}).status_code==400
        assert write(teacher,'/api/login',{'email':'teacher@test.invalid','password':'long-teacher-password-123','school_slug':'testschool'}).status_code==200
        rows=teacher.get('/api/learners').json()
        assert len(rows)==1 and rows[0]['class_name']=='4A'
        assert teacher.get('/api/members').status_code==403
        assert write(admin,'/api/offences',{'code':'B01','name':'Fighting','category':'Safety','severity':3}).status_code==201
        base={'offence_id':1,'location':'Classroom','description':'Fictional event','immediate_action':'Referral'}
        assert write(teacher,'/api/incidents',dict(base,learner_id=2)).status_code==403
        incident=write(teacher,'/api/incidents',dict(base,learner_id=1))
        assert incident.status_code==201 and incident.json()['requires_review']
        tasks=admin.get('/api/review-tasks').json()
        assert len(tasks)==1
        assert write(admin,'/api/incidents/1/review',{'status':'verified','notes':'Reviewed'},method='patch').status_code==200
        assert write(admin,'/api/parent-contacts',{'learner_id':1,'method':'Phone','purpose':'Concern','outcome':'Meeting planned'}).status_code==201
        assert admin.get('/api/reports/summary').json()['by_grade']=={'4':1}
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
