import importlib.util
import json
from pathlib import Path


def test_sample_excludes_validation_users_texts_and_outcomes(tmp_path):
    spec=importlib.util.spec_from_file_location('audit_data',Path(__file__).resolve().parents[1]/'audit_data.py')
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    def row(ticket,user,text):
        return {'ticket_id':ticket,'kind':'report','reporter_hash':user,'lang':'ru',
                'messages':[{'role':'player','text':text},{'role':'admin','text':'private administrator answer'}],
                'verdict':'approved','punishment':'mut','violation':'9.9','category':'report.question','priority':'p3'}
    train=[row('1','same-user','one'),row('2','different','same text'),row('3','independent','mechanics question')]
    valid=[row('4','same-user','same text')]
    for name,rows in [('train',train),('valid',valid)]:
        (tmp_path/name).write_text(''.join(json.dumps(x)+'\n' for x in rows),encoding='utf-8')
    report,sample=mod.audit(tmp_path/'train',tmp_path/'valid',120,42)
    assert report['train']['count']==3 and report['overlap']['reporters']==1
    assert report['overlap']['valid_rows_with_train_text']==1
    assert len(sample)==1 and sample[0]['input']['ticket_id']=='3'
    assert all(m['role']!='admin' for m in sample[0]['input']['messages'])
    assert not {'verdict','punishment','violation','category','priority'} & sample[0]['input'].keys()
    assert sample[0]['labels']['category'] is None
    assert sample[0]['status']=='unlabeled'
