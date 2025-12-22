from homework_agent.utils.prompt_manager import get_prompt_manager


def test_prompt_manager_loads_math_prompt():
    pm = get_prompt_manager()
    text = pm.render("math_grader_system.yaml")
    assert "Math Homework Grading Agent" in text


def test_prompt_manager_loads_socratic_prompt():
    pm = get_prompt_manager()
    text = pm.render("socratic_tutor_system.yaml")
    assert "苏格拉底式" in text or "辅导" in text

