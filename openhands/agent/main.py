"""
Main Entry Point for Enterprise AI Code Review Agent.

This script orchestrates the entire review workflow:
1. Loads configuration and policies.
2. Connects to GitLab to fetch Merge Request details.
3. Applies Smart Triage to filter files (SKIP, AUTO_APPROVE, CRITICAL).
4. Invokes ReviewAgent for deep analysis (Semantic, SAST, Quality).
5. Evaluates Review Gate (Pass/Fail/Warn).
6. Exports Metrics (Prometheus/GitLab).
7. Posts results to GitLab MR.

Usage:
    python3 main.py --project-id <ID> --mr-iid <IID> --policy <path>
"""
import os
import argparse
import sys
import time

# Ensure package is found
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

package_parent_dir = os.path.dirname(os.path.dirname(current_dir))
if package_parent_dir not in sys.path:
    sys.path.insert(0, package_parent_dir)


from openhands.agent.provider.vllm_provider import LLMFactory
from openhands.agent.memory.strategies import SmartMemoryStrategy
from openhands.agent.core.agent import ReviewAgent
from openhands.agent.triage.review_triage import ReviewTriage, ReviewDecision
from openhands.agent.config.config_loader import load_policy
from openhands.agent.gate.review_gate import ReviewGate
from openhands.agent.metrics.collector import MetricsCollector, ReviewMetrics

import gitlab

def get_gitlab_client():
    url = os.getenv("GITLAB_URL")
    token = os.getenv("GITLAB_TOKEN")
    if not token:
        print("[WARNING] GITLAB_TOKEN not set in environment strings! Using mock/unauthenticated mode may fail.")
    return gitlab.Gitlab(url, private_token=token, ssl_verify=False)

def main():
    # Suppress noise
    import logging
    logging.getLogger("tiktoken").setLevel(logging.ERROR)
    logging.getLogger("langchain").setLevel(logging.ERROR)
    logging.getLogger("openai").setLevel(logging.ERROR)
    import warnings
    warnings.filterwarnings("ignore", message=".*model not found.*")

    parser = argparse.ArgumentParser(description="Autonomous Enterprise Code Review Agent")
    parser.add_argument("--project-id", type=int, default=os.getenv("CI_PROJECT_ID"), help="GitLab Project ID")
    parser.add_argument("--mr-iid", type=int, default=os.getenv("CI_MERGE_REQUEST_IID"), help="Merge Request IID")
    parser.add_argument("--policy", type=str, help="Path to custom policy YAML")
    args = parser.parse_args()
    
    if not args.project_id or not args.mr_iid:
        print("Missing Project ID or MR IID.")
        return

    # 1. Initialize Components & Policy
    print(f"[INFO] Initializing Agent Components for Project {args.project_id}, MR !{args.mr_iid}...")
    
    # Load policy
    policy = load_policy(args.policy)
    print(f"[INFO] Review Policy loaded (v{policy.version})")
    
    # Init components
    provider = LLMFactory.create_provider("vllm")
    memory = SmartMemoryStrategy(provider)
    agent = ReviewAgent(provider, memory)
    triage = ReviewTriage(policy)
    gate = ReviewGate(policy)
    metrics_collector = MetricsCollector()
    
    # 2. Connect to GitLab
    try:
        gl = get_gitlab_client()
        project = gl.projects.get(args.project_id)
        mr = project.mergerequests.get(args.mr_iid)
        print(f"[INFO] Connected to GitLab. Project: {project.name}, MR: !{args.mr_iid}")
        
        changes = mr.changes()
        reviews = []
        metrics_list = []
        overall_status = "pass"
        blocking_issues = []
        
        change_count = len(changes['changes'])
        print(f"[INFO] Found {change_count} changes.")
        
        if change_count == 0:
            print("[WARNING] No changes found.")
            return

        # Pre-collect all changed files for context
        all_changed_files = [c['new_path'] for c in changes['changes'] if not c['deleted_file']]

        for change in changes['changes']:
            new_path = change['new_path']
            if change['deleted_file']:
                print(f"[INFO] Skipping deleted file: {new_path}")
                continue
                
            diff = change['diff']
            start_time = time.time()
            
            # Fetch full content for context
            full_content = None
            try:
                f = project.files.get(file_path=new_path, ref=mr.sha)
                full_content = f.decode().decode('utf-8')
            except Exception:
                pass

            # 3. Triage Decision
            triage_result = triage.decide(diff, new_path, full_content)
            print(f"[TRIAGE] {new_path}: {triage_result.decision.value} ({triage_result.reason})")
            
            # 4. Action based on decision
            review_text = ""
            gate_eval = None
            
            if triage_result.decision == ReviewDecision.SKIP:
                continue
                
            elif triage_result.decision == ReviewDecision.AUTO_APPROVE:
                reviews.append(f"## ✅ Auto-Approved: `{new_path}`\n> {triage_result.reason}\n\n---\n")
                
            else:
                # FULL_REVIEW, QUICK_SCAN, CRITICAL -> Run Agent
                print(f"[AGENT] analyzing {new_path}...")
                # Pass all_changed_files for context awareness
                review_text = agent.review_diff(new_path, diff, full_content, other_files=all_changed_files)
                reviews.append(f"## Review for `{new_path}`\n\n{review_text}\n\n---\n")
                
                # 5. Evaluate Gate
                gate_eval = gate.evaluate(review_text)
                if gate_eval.result == "fail":
                    overall_status = "fail"
                    blocking_issues.extend([f"{new_path}: {r}" for r in gate_eval.blocking_issues])
            
            # 6. Record Metrics
            duration = int((time.time() - start_time) * 1000)
            metric = ReviewMetrics(
                project_id=str(args.project_id),
                mr_id=str(args.mr_iid),
                files_analyzed=1,
                lines_analyzed=len(diff.splitlines()),
                triage_decisions={triage_result.decision.value: 1},
                gate_result=gate_eval.result.value if gate_eval else "pass",
                quality_score=gate_eval.scores.get('quality', 0) if gate_eval else 0,
                duration_ms=duration
            )
            metrics_collector.record(metric)
            
        # Post MR Comment
        if reviews:
            header = "# 🤖 AI Review Report\n\n"
            
            # Gate Summary
            if overall_status == "fail":
                header += "### ⛔ Pipeline BLOCKED\n"
                for issue in blocking_issues:
                    header += f"- 🔴 {issue}\n"
            else:
                header += "### ✅ Pipeline PASSED\n"
            
            header += f"\n**Policy v{policy.version}** | **Analyzed**: {len(reviews)} files\n\n---\n"
            
            body = header + "\n".join(reviews)
            mr.notes.create({'body': body})
            print("[INFO] Review posted to GitLab.")
        
        # Export metrics
        metrics_collector.export_gitlab_metrics("metrics.txt")
        print("[INFO] Metrics exported.")
        
        # Exit with gate status
        if policy.gate.fail_pipeline_on_critical and overall_status == "fail":
            print("[GATE] Pipeline failed due to critical issues.")
            sys.exit(1)
            
    except Exception as e:
        print(f"[ERROR] Critical failure: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
