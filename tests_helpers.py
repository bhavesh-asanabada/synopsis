"""Deterministic retrieval fixture for workflow tests; real inference has a separate test."""
import numpy as np

def semantic_fixture(texts):
    vectors=[]
    for text in texts:
        t=text.casefold()
        vectors.append([1+sum(w in t for w in ('data','sample','reliability','scarce','variance','participants')),
                        1+sum(w in t for w in ('garden','apple','orange','orchard')),
                        0.1])
    return np.array(vectors,dtype=float)
