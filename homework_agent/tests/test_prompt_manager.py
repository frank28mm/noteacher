from homework_agent.utils.prompt_manager import PromptManager, get_prompt_manager


def test_prompt_manager_loads_math_prompt():
    pm = get_prompt_manager()
    text = pm.render("math_grader_system.yaml")
    assert "Math Homework Grading Agent" in text


def test_prompt_manager_loads_socratic_prompt():
    pm = get_prompt_manager()
    text = pm.render("socratic_tutor_system.yaml")
    assert "苏格拉底式" in text or "辅导" in text


def test_prompt_manager_variant_resolution(tmp_path):
    base = tmp_path / "p.yaml"
    base.write_text("id: p\nversion: 1\ntemplate: |\n  base\n", encoding="utf-8")
    variant = tmp_path / "p__B.yaml"
    variant.write_text(
        "id: p\nversion: 2\ntemplate: |\n  variant_b\n", encoding="utf-8"
    )

    pm = PromptManager(str(tmp_path))
    assert pm.render("p.yaml").strip() == "base"
    assert pm.render("p.yaml", variant="B").strip() == "variant_b"
    assert pm.render("p.yaml", variant="A").strip() == "base"

    meta_b = pm.meta("p.yaml", variant="B")
    assert meta_b.get("id") == "p"
    assert meta_b.get("version") == 2
    assert meta_b.get("variant") == "B"
