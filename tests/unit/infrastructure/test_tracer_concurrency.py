"""Step 3 — a tracer that survives threads.

The thing most likely to be subtly wrong under concurrency, and also the
instrument every later concurrency bug will be diagnosed with. Getting it wrong
would mean debugging the committee with a broken microscope.
"""

import threading

from code_reviewer.domain.trace import SpanKind
from code_reviewer.infrastructure.concurrency.thread_pool import ThreadPoolRunner
from code_reviewer.infrastructure.observability.tracer import SpanRecorder


def _by_id(tracer: SpanRecorder):
    return {span.span_id: span for span in tracer.trace().spans}


def test_a_worker_span_attaches_to_the_span_that_submitted_it():
    """Not to whatever the worker's own thread had open — which is nothing."""
    tracer = SpanRecorder()

    with tracer.span(SpanKind.FILE, "a.py") as parent:

        def work():
            with tracer.bind(parent):
                with tracer.span(SpanKind.AGENT, "security"):
                    pass

        thread = threading.Thread(target=work)
        thread.start()
        thread.join()

    agent = next(span for span in tracer.trace().spans if span.kind is SpanKind.AGENT)
    assert agent.parent_id == parent


def test_a_worker_can_still_nest_inside_its_own_bound_span():
    tracer = SpanRecorder()

    with tracer.span(SpanKind.FILE, "a.py") as parent:

        def work():
            with tracer.bind(parent):
                with tracer.span(SpanKind.AGENT, "security") as agent:
                    with tracer.span(SpanKind.TOOL, "grep") as tool:
                        assert tool.startswith(f"{agent}.")

        thread = threading.Thread(target=work)
        thread.start()
        thread.join()

    tool = next(span for span in tracer.trace().spans if span.kind is SpanKind.TOOL)
    agent = next(span for span in tracer.trace().spans if span.kind is SpanKind.AGENT)
    assert tool.parent_id == agent.span_id


def test_four_threads_under_one_parent_produce_a_clean_tree():
    tracer = SpanRecorder()

    with tracer.span(SpanKind.FILE, "a.py") as parent:

        def work(name):
            def run():
                with tracer.bind(parent):
                    with tracer.span(SpanKind.AGENT, name):
                        with tracer.span(SpanKind.MODEL, "invoke"):
                            pass

            return run

        threads = [threading.Thread(target=work(f"agent-{index}")) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    trace = tracer.trace()

    assert trace.anomalies == ()
    root = trace.tree()
    assert root.span.span_id == parent
    assert len(root.children) == 4
    assert all(len(child.children) == 1 for child in root.children)


def test_binding_to_nothing_is_a_no_op():
    """So a caller need not branch on whether tracing is on."""
    tracer = SpanRecorder()

    with tracer.bind(""):
        with tracer.span(SpanKind.REVIEW, "run"):
            pass

    assert _by_id(tracer)["1"].parent_id == ""


def test_a_bound_span_is_not_recorded_as_a_span_of_its_own():
    tracer = SpanRecorder()

    with tracer.span(SpanKind.FILE, "a.py") as parent:
        with tracer.bind(parent):
            pass

    assert len(tracer.trace()) == 1


def test_the_stack_is_restored_even_when_the_body_raises():
    tracer = SpanRecorder()

    with tracer.span(SpanKind.FILE, "a.py") as parent:
        try:
            with tracer.bind(parent):
                raise RuntimeError("no")
        except RuntimeError:
            pass
        assert tracer.current_span_id == parent


def test_no_span_is_lost_under_contention():
    """AC-9. The assertion is on the result, not on the absence of a crash."""
    tracer = SpanRecorder()
    spans_per_thread = 25
    threads = 8

    with tracer.span(SpanKind.REVIEW, "run") as parent:

        def work():
            with tracer.bind(parent):
                for index in range(spans_per_thread):
                    with tracer.span(SpanKind.TOOL, f"tool-{index}"):
                        pass

        workers = [threading.Thread(target=work) for _ in range(threads)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

    trace = tracer.trace()

    assert len(trace) == threads * spans_per_thread + 1
    assert len({span.span_id for span in trace.spans}) == len(trace)
    assert trace.anomalies == ()


def test_the_pool_and_the_tracer_work_together():
    tracer = SpanRecorder()

    with tracer.span(SpanKind.FILE, "a.py") as parent:

        def make(name):
            def task():
                with tracer.bind(parent):
                    with tracer.span(SpanKind.AGENT, name):
                        return name

            return task

        outcomes = ThreadPoolRunner(max_workers=4).run_all([make(f"agent-{index}") for index in range(4)])

    assert [outcome.value for outcome in outcomes] == [f"agent-{index}" for index in range(4)]
    assert tracer.trace().anomalies == ()
    assert len(tracer.trace().tree().children) == 4


def test_two_threads_never_receive_the_same_identifier():
    tracer = SpanRecorder()
    seen: list[str] = []
    lock = threading.Lock()

    with tracer.span(SpanKind.REVIEW, "run") as parent:

        def work():
            with tracer.bind(parent):
                for _ in range(20):
                    span_id = tracer.start(SpanKind.TOOL, "t")
                    with lock:
                        seen.append(span_id)
                    tracer.finish(span_id)

        workers = [threading.Thread(target=work) for _ in range(6)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

    assert len(set(seen)) == len(seen)
