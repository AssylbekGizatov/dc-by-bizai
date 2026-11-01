import numpy as np
from app.trained import ComplaintModel,CHAR,WORD

def test_binary_single_logit_uses_both_classes():
    width=CHAR.n_features+WORD.n_features
    for intercept,expected in [(3,'report.help'),(-3,'report.question')]:
        model=ComplaintModel(['report.question','report.help'],np.zeros((1,width)),np.array([intercept]),np.ones(width))
        label,probability=model.predict('synthetic test')
        assert label==expected and .9<probability<1
