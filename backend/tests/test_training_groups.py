from app.trained import exclude_groups,train_reports
import json
import pytest

def test_holdout_removes_transitive_user_text_group_including_unlabelled_bridge():
    rows=[{'ticket_id':'test','reporter_hash':'a','text':'one'},
          {'ticket_id':'bridge','reporter_hash':'a','text':'two'},
          {'ticket_id':'leak','reporter_hash':'b','text':'TWO'},
          {'ticket_id':'safe','reporter_hash':'c','text':'three'}]
    assert [r['ticket_id'] for r in exclude_groups(rows,{'test'})]==['safe']

def test_nested_gold_without_features_fails_instead_of_training_empty_text(tmp_path):
    p=tmp_path/'gold.jsonl'
    p.write_text(json.dumps({'kind':'report','split':'train','labels':{'category':'report.help'}}))
    with pytest.raises(ValueError,match='joined player_text'):
        train_reports(str(p))
