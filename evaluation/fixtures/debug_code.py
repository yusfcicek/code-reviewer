"""A debugger left behind, which is the defect, plus a flag that is not."""

import pdb


def parse(payload: str) -> dict:
    pdb.set_trace()
    return {"payload": payload}


VERBOSE = True
