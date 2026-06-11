from autoresearch.agents import (
    ResearchWorkflow,
    ResearchWorkflowStage,
    WorkflowCheckpointStore,
)


def test_langgraph_workflow_pauses_and_resumes_from_checkpoint(tmp_path):
    store = WorkflowCheckpointStore(tmp_path)
    workflow = ResearchWorkflow(store)

    paused_state = workflow.start(
        project_id="autoresearch-system",
        workflow_id="workflow-001",
        pause_after=ResearchWorkflowStage.LITERATURE,
    )

    assert paused_state.paused is True
    assert paused_state.stage is ResearchWorkflowStage.HYPOTHESIS
    assert paused_state.completed_steps == (ResearchWorkflowStage.LITERATURE,)
    assert store.path_for("workflow-001").exists()

    checkpoint = store.load("workflow-001")
    assert checkpoint == paused_state

    resumed_state = workflow.resume("workflow-001")

    assert resumed_state.paused is False
    assert resumed_state.stage is ResearchWorkflowStage.COMPLETE
    assert resumed_state.completed_steps == (
        ResearchWorkflowStage.LITERATURE,
        ResearchWorkflowStage.HYPOTHESIS,
        ResearchWorkflowStage.EXPERIMENT,
        ResearchWorkflowStage.REPORT,
    )
