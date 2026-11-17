# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

## Case: `seeded_regression C-002@11` (T02)

Output (rút gọn):
```
== seeded_regression C-002@11  lab8 grader: FAIL (status resolved != denied)
   1 handoff            {"request_id": "REQ-C-002", "task": "check_applicable_policy", ...}
   2 investigator       {"lookup_order": {"visible": true, "order": {"order_id": "O-202", "status": "delivered", "delay_days": 2, ...}}}
   3 model_override     {"delay_days": 5}
   4 quote              {"amount_vnd": 20000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"], ...}
   5 refund_history     {"refund_count": 0, "refunded_vnd": 0}
   6 reply              {"text": "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."}
-- ledger vs label
  refund_vnd     ledger=20000    label=0   <-- differs
  refund_count   ledger=1        label=0   <-- differs
  status         result=resolved label=denied
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run `E-seeded_regression-20261117-f7a1` (`src/reports/eval_seeded_regression.json`, item `E-002`, cả 5 seed đều fail) |
| Triệu chứng | `pass_rate` FAIL (status resolved ≠ denied), `refund_amount_correct` FAIL (ledger 20.000 ≠ nhãn 0), `db_fact_kept` FAIL (1 event override). Reply "đã hoàn 20.000đ" **khớp ledger**, nên `reply_matches_ledger` không bắt được: lỗi nằm ở quyết định, không nằm ở lời văn. |
| Bước sai đầu tiên | **Event 3** `model_override {"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 (handoff) đúng contract `handoff.v1`, chỉ cấp tool đọc. Event 2 (investigator) đọc đúng DB: đơn O-202 `delay_days: 2`, tức dưới ngưỡng 3 ngày nên không được hoàn. Event 3 thay số 2 của DB bằng số 5 trong ticket ("Đơn giao trễ 5 ngày"). Event 4 (quote 20.000) là hệ quả **đúng** của input sai: `compute_compensation` tính đúng với `delay_days=5`. |
| Failure mode | **FM-03 ticket_trust** (layer model/prompt) |
| Đối chứng | `fixed C-002@11`: event 2 giống hệt, **không có** `model_override`, event 3 là `quote {"amount_vnd": 0, "reason": "no_entitlement"}` → `denied`, ledger 0, lab8 PASS. Swarm tham chiếu cũng mắc đúng lỗi này ở seed 55 (C-002@55), là nguồn duy nhất làm baseline < 1.0. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_seeded_regression_c002_first_wrong_step_is_model_override` kiểm event override đứng ngay sau investigator, DB=2 và ticket=5, đồng thời `db_fact_kept`, `refund_amount_correct`, `pass_rate` đều False. `test_fixed_c002_keeps_db_fact_and_denies` kiểm bản fix không override và mọi grader xanh. Đã chạy: fail đúng trên variant lỗi, pass trên `fixed` (`python -m pytest -q -m student -o addopts= -k trace_case`). Item `E-002` trong eval set có `provenance.from_trace` trỏ tới trial này. |
| Chưa chắc chắn | Trace chỉ cho thấy *agent đã* override, không cho biết *vì sao* (MockLLM là luật cứng theo công tắc, không có lý do ngôn ngữ). `quiet_override` (cùng lỗi, không ghi event) sẽ làm `db_fact_kept` mù; khi đó chỉ grader mức kết quả (`refund_amount_correct`, `pass_rate`) còn bắt được. Đã thử: variant tự tạo `quiet_override` vẫn bị gate chặn qua `refund_amount_correct` và slice `adversarial`/`denial`. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
