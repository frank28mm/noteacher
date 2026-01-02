from homework_agent import demo_ui


def test_fmt_ms_basic():
    assert demo_ui._fmt_ms(None) == "n/a"
    assert demo_ui._fmt_ms(0) == "0ms"
    assert demo_ui._fmt_ms(999) == "999ms"
    assert demo_ui._fmt_ms(1000) == "1.00s"
    assert demo_ui._fmt_ms(1500) == "1.50s"
    assert demo_ui._fmt_ms(60000) == "60.0s"


def test_render_timing_panel_contains_key_fields():
    md = demo_ui._render_timing_panel_md(
        upload_id="sub_123",
        session_id="sess_abc",
        timing_ctx={
            "upload_ms": 12,
            "grade_submit_ms": 34,
            "grade_queue_wait_ms": 56,
            "grade_worker_elapsed_ms": 78,
            "grade_wall_ms": 90,
            "qbank_meta": {
                "meta": {
                    "timings_ms": {
                        "grade_total_duration_ms": 1111,
                        "llm_aggregate_call_ms": 2222,
                    },
                    "llm_trace": {
                        "ark_response_id": "resp_1",
                        "ark_image_process_requested": True,
                        "grade_image_input_variant": "url",
                    },
                }
            },
        },
        grade_job={"status": "done", "elapsed_ms": 123},
        report_job={"status": "pending"},
    )

    assert "submission_id: `sub_123`" in md
    assert "session_id: `sess_abc`" in md
    assert "upload_ms:" in md
    assert "grade_total_duration_ms:" in md
    assert "ark_response_id:" in md
