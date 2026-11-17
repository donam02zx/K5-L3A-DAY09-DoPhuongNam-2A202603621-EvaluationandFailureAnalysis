# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend REPLAY, không cần key). FAIL là lớp dương: việc của judge là **tìm lỗi**.

| Tiêu chí | n | κ | Precision | Recall | Ma trận (tp/fp/fn/tn) | Tỉ lệ FAIL quan sát → hiệu chỉnh (Rogan-Gladen) | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | 24 / 4 / 6 / 66 | 0.28 → 0.30 | **Đạt** | **dùng** (chỉ cho tone, không chặn tiền) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | 9 / 0 / 21 / 70 | 0.09 → 0.30 | **Không đạt** (κ, R) | **loại** |

## ≥5 case audit thủ công

### tone_ok (10 bất đồng)
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã với khách khiếu nại. Rubric thêm: *xưng hô phải là "LogiX" / "anh/chị"; cấm "em", "bạn", "nha/nhé"* kèm ví dụ âm. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ…" | PASS | FAIL | Người | Cùng lỗi xưng hô ("bạn"). Gộp chung vào quy tắc xưng hô ở #1. |
| 3 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ nhìn kính ngữ đầu câu. Rubric thêm: *câu mệnh lệnh / gạt khách ("không cần nhắn thêm") = FAIL dù có "Dạ"*. |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi". Rubric ghi rõ: *xin lỗi không bắt buộc; ngắn gọn, đủ ý, lịch sự = PASS*. |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | Người | "refund" nằm trong từ điển CS LogiX cho phép. Đưa danh sách thuật ngữ được phép vào prompt judge. |
| 6 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | Người, nhưng **sai tiêu chí** | Đây là lỗi *nội dung* (hứa ngoài kết quả hệ thống), không phải tone. Chuyển sang grader code: reply không được hứa số tiền/hành động ngoài ledger (cùng họ FM-08). |
| 7 | H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Rubric thêm: *emoji cười trong ngữ cảnh khiếu nại = FAIL*. |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** (theo note: người đọc nhầm ticket) | Đây là lỗi nhãn người. Sửa nhãn trong bộ calibration tiếp theo và ghi lại lý do. Sau khi sửa, fn/fp của judge giảm 1. |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ…" | FAIL | PASS | Người (lỗi gõ nhẹ) | Rubric: *lỗi gõ không làm sai nghĩa và không thô lỗ thì không FAIL tone*. |
| 10 | H-094 "Da, LogiX da hoan 40.000đ… xin loi…" | PASS | FAIL | Người | Mất dấu tiếng Việt (dịch máy) là trải nghiệm kém. Rubric thêm: *tiếng Việt không dấu = FAIL*. |

### helpful (mẫu 6 trong 21 bất đồng; cả 21 đều là judge PASS / người FAIL)
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 1 | HL-015 "đã hoàn 55.000đ cho đơn O-112" (ledger 40.000) | PASS | FAIL | Người | Judge **không thấy ledger**, nên không thể biết số tiền sai. |
| 2 | HL-016 xin lỗi dài 3 câu + "đã hoàn 55.000đ" (ledger 35.000) | PASS | FAIL | Người | Câu dài, nhiều xin lỗi bị judge chấm là "helpful" (verbosity bias), trong khi số tiền sai. |
| 3 | HL-020 "đã hoàn 90.000đ" (ledger 120.000) | PASS | FAIL | Người | Nói *thiếu* tiền cũng không bị bắt: judge không có nguồn sự thật. |
| 4 | HL-043 xin lỗi lặp + "35.000đ" (ledger 20.000) | PASS | FAIL | Người | Đúng mẫu FM-08: reply nói số khác ledger, bị lời xin lỗi dài che đi. |
| 5 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Không nói kết quả, không nói số tiền: vô ích, nhưng judge vẫn PASS. |
| 6 | HL-091 / HL-097 "Ok bạn, đơn … xử lý rồi nhé." | PASS | FAIL | Người | Cùng mẫu với #5, lặp lại ⇒ lỗi hệ thống của judge chứ không phải ngẫu nhiên. |

## Kết luận
- **tone_ok: dùng được.** κ=0.757, P=0.857, R=0.80 đều qua sàn. 9/10 bất đồng là judge sai theo 4 mẫu có thể sửa bằng rubric: xưng hô, mệnh lệnh, emoji, không dấu. 1/10 là nhãn người sai (H-081). Tỉ lệ FAIL quan sát 0.28 sau Rogan-Gladen là 0.30. Chỉ dùng làm metric **theo dõi**, không chặn release: tone không chạm tới tiền.
- **helpful: loại, không được dùng làm gate.** Ma trận nhầm lẫn tp=9, fp=0, **fn=21**, tn=70: R=0.30 và κ=0.375 thấp hơn sàn. Judge gần như luôn nói PASS. Precision 1.0 chỉ là ảo giác do judge hiếm khi nói FAIL. Tỉ lệ FAIL quan sát 0.09 trong khi thực tế khoảng 0.30, tức gate dùng judge này sẽ **bỏ lọt khoảng 70% reply tệ**. Nguyên nhân gốc: phần lớn lỗi "không helpful" là **số tiền trong reply khác ledger**, mà judge không được nhìn ledger, cộng thêm verbosity bias với câu xin lỗi dài. Thay thế: kiểm số tiền bằng **code** qua `reply_matches_ledger` (FM-08, metric chặn). Phần "reply rỗng, vô ích" cần rubric mới cùng một vòng calibration mới trước khi dùng lại.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (judge đã "thấy" bộ này), và một nhãn người đã sai (H-081). Cần một bộ nhãn người mới, gán độc lập (≥2 người, đo κ giữa người), làm held-out thật trước khi tin số calibration.
