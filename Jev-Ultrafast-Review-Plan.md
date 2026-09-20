# Jev Ultrafast — Code Review & Implementation Plan

วันที่รีวิว: 20 กันยายน 2026

Repository: https://github.com/Bigthap/jev-ultrafast

Commit: `4ebed43fa98646366d9f72aa2cc3720f9a2472bd`

## ข้อสรุป

ควรรักษาแกน browser agent เดิม แล้วปรับชั้น voice/session ให้มี lifecycle ที่แน่นอนก่อนเพิ่มฟีเจอร์หรือเปลี่ยนโมเดล ความลื่นไหลที่ต้องการเกิดจากการเลือกแท็บถูก หยุดได้จริง ไม่ทำคำสั่งซ้อน ไม่ reload โดยไม่จำเป็น และบอกผลตามหลักฐาน ก่อนจะเป็นเรื่องความเร็ว inference

ขอบเขตแผน: ผู้ช่วยสั่งเบราว์เซอร์ด้วยเสียงไทย/อังกฤษบน desktop โดยให้ Windows เป็นแพลตฟอร์มหลักของรุ่นแรก ไม่ถือว่าเป็นระบบควบคุมทุกแอปบน desktop และไม่ตั้งเป้าว่าทำงานได้กับทุกเว็บไซต์ทันที

หลักฐานมาจากโค้ดใน commit ข้างต้นและการตรวจแบบ offline ไม่ได้วัดความแม่นยำ STT จริง ความเร็ว TypeSafe API จริง หรือใช้งานกับไมโครโฟน/Chrome ของผู้ใช้ ตัวเลขเป้าหมายด้านล่างเป็นเกณฑ์ที่เสนอ ไม่ใช่ผล benchmark

## สิ่งที่ควรรักษา

- `model.py`: เลือก operation และ operation-specific target ใน request เดียว และใช้เฉพาะ target head ของ operation ที่ถูกเลือก
- `snapshot.js` / `browser.py`: ผูก action กับ observed DOM node พร้อม freshness guard และ hit-test ก่อน input
- `agent.py`: consume decision ก่อน mutation; เก็บ text-helper result สำหรับ stale retry เฉพาะเมื่อ context เหมือนเดิม
- การบันทึก action ก่อน observation ถัดไป ช่วยไม่ให้ action ที่เกิดขึ้นแล้วหายจาก history หาก observation ถูก navigation ขัดจังหวะ
- screenshot ไม่อยู่ใน default model loop จึงไม่ควรเพิ่มเข้าทุก step
- เทสต์ตรวจ model contract และ mutation interruption เป็นฐานที่ดีสำหรับต่อยอด

## ข้อค้นพบจากโค้ด

| ID | ระดับ | หลักฐาน | ผลกระทบ / วิธีแก้ |
|---|---|---|---|
| R01 | P0 | `voice_gui.py:219–245`, `voice_listener.py:26–49`, `voice.py:80` | UI ตั้ง `_stop_event` แต่ recorder ไม่รับหรืออ่าน event ปุ่ม Finish จึงไม่หยุดอัดตามที่แสดง ต้องส่ง cancellation/stop token ถึง recorder |
| R02 | P0 | `voice_gui.py:244–283`; `voice_listener.py:28–57` | GUI ยังไม่ busy ระหว่าง STT และ send-text ไม่ตรวจ recording; listener เปลี่ยน recording flag ทั้งที่ stream อาจยังอยู่ เปิดทางให้งาน/stream ซ้อน ต้องมี controller ที่รับคำสั่งแบบ atomic และ worker เดียว |
| R03 | P0 | `voice.py:289–304`, `browser.py:29–44` | ใช้ `pages[0]` หรือ tab แรกที่ URL มี substring ของ domain ไม่ได้ยืนยัน active tab และอาจ match domain ใน query/path ต้องใช้ targetId ที่เลือกชัดเจนและ compare parsed hostname |
| R04 | P0 | `browser.py:60–68`, `voice.py:336–339` | การ attach ครั้งแรกด้วย URL ที่มี path จะเรียก navigate แม้ intent เป็น in_page เสี่ยง reload และทำ draft หาย แยก attach-existing กับ navigate เป็นคนละ API |
| R05 | P0 | `voice.py:277–280` | intent model ล้มเหลวแล้ว fallback เป็น navigate ไป Google/Flights แม้ผู้ใช้เพียงสั่งในหน้าเดิม ต้อง preserve context และรายงานข้อผิดพลาด ไม่เปลี่ยนเว็บจาก exception |
| R06 | P0 | `browser.py:168–174`, `Agent(... reuse_tab=True)` | close ไม่แยก borrowed tab กับ owned tab; default agent สามารถปิดแท็บเดิมที่ยืมมาได้ ส่วน voice ใช้ keep_open=True จึงไม่เข้าทางปิดนี้โดยตรง ต้อง track ownership และ detach session |
| R07 | P1 | `voice.py:80,159,195–200` | รอเงียบ 1.6s แล้วค่อย POST WAV ทั้งก้อน จากนั้น intent และ Jev ทำตามลำดับ จึงยังไม่ใช่ streaming voice pipeline |
| R08 | P1 | `voice.py:146–165,170–187`, `model.py:15–28` | STT ใช้ top-level httpx.post ไม่มี client reuse ที่ชั้นนี้; error ถูกกลืน; fallback รอ provider แรกก่อน; ไม่มี deadline ทั้ง command ต้องมี typed errors, pooled client, per-stage/overall deadline |
| R09 | P1 | `voice.py:265–276` | ตรวจ JSON โดยไม่มี schema เข้มงวด และแปลงทุก same-domain navigation เป็น in_page ทำให้ explicit path navigation สูญหาย ต้อง validate action_type/url/goal และรักษาเจตนา explicit navigation |
| R10 | P1 | `voice.py:225,241–248,277–280` | hardcode Flights และปี 2026 ใน generic voice layer ขัดกับเป้าหมาย generic agent และเสี่ยงวันที่ผิด ให้เวลา/timezone ปัจจุบันเป็น context และย้าย Flights ไป example |
| R11 | P1 | `voice.py:341–356`, `voice_gui.py:319–324` | ครบ max_steps อาจคืน ready แต่ UI แสดง Done; DONE จากโมเดลยังไม่มี independent verifier ของ voice session แยก succeeded/unverified/blocked/budget_exceeded/cancelled |
| R12 | P1 | `agent.py:177–193` | set_goal reset history/decisions แต่ไม่ reset text_calls และ elapsed_ms ทำให้ metrics ปะปนระหว่าง turns แยก per-turn กับ session totals |
| R13 | P1 | `voice.py:344–346` | callback อ่าน history[-1] ทุก tick แม้ไม่มี action ใหม่ เช่น stale retry หรือ DONE จึงมีโอกาส log action เก่าซ้ำ ใช้ event_id/step_id และ emit เฉพาะ event ใหม่ |
| R14 | P1 | `browser.py:77–83` | navigate poll readyState complete โดยไม่ผูกกับ document/navigation identity และไม่ตรวจ errorText อย่างชัดเจน ควรติดตาม navigation ที่ร้องขอและรอ readiness ที่งานต้องการ |
| R15 | P2 | `snapshot.js`, `browser.py:198` | จำกัด 250 actions; ยังไม่ traverse frames/shadow roots; scroll ใช้พิกัดคงที่ 550,650 ขยายตาม task benchmark เริ่ม keyboard, nested scroll และ tab lifecycle |
| R16 | P2 | `pyproject.toml`, README, tests | voice dependencies ติดตั้งพร้อม core เสมอ; README ยังแนะนำ upstream clone และไม่มี voice setup; voice session tests ใช้ patch.start โดยไม่ stop และ mock ไม่จำลอง loop lifecycle จริง เพิ่ม optional extras/CI/เอกสาร |

จุดที่ยังต้องพิสูจน์ด้วย instrumentation: ต้นทุน full DOM scan ใน fresh/observe, สัดส่วนเวลาของ STT กับ intent, ความแม่นยำ mixed Thai-English, ความสัมพันธ์ระหว่าง model confidence กับ action correctness, และผลลัพธ์ของ live sites ที่ DOM เปลี่ยนต่อเนื่อง

## สถาปัตยกรรมเป้าหมาย

ให้ Tkinter GUI และ hotkey CLI ส่ง event เข้า VoiceController ตัวเดียว Controller คุม AudioCapture, STT adapter, IntentRouter, BrowserSession และ Agent ผ่าน worker ที่จัดลำดับงาน ไม่ให้ frontend แต่ละตัวมี execution loop แยกกัน

สถานะหลัก: idle, recording, transcribing, resolving_intent, executing, verifying, succeeded, cancelled, blocked, error, budget_exceeded และ unverified

ทุก turn มี turn_id, cancellation token, deadline, targetId และ event sequence ของตัวเอง Controller อนุญาตเพียงหนึ่ง turn ที่ทำ browser mutation ได้ในขณะหนึ่ง ผลจาก request เก่าที่กลับมาหลัง cancel ต้องถูกทิ้งก่อนเข้าสู่ executor

กำหนด Stop สองชนิดให้ชัด: Finish recording ส่ง audio ที่มีไปถอดเสียง ส่วน Cancel task ยุติ turn และป้องกัน action ถัดไป การ cancel ไม่สามารถย้อน action ที่ส่งถึง browser ไปแล้วได้ และต้องรายงาน action ที่เกิดขึ้น/ยังไม่ทราบผลตามจริง

UI รับ event ผ่าน queue ที่ main thread poll ด้วย root.after; การปิดหน้าต่างต้อง cancel, ปิด stream, detach CDP, ปิด HTTP client และหยุด worker อย่างมีขอบเขตเวลา

## Roadmap ที่นำไปเปิดเป็น PR ได้

### PR 1 — Lifecycle, Finish และ Cancel (P0)

- สร้าง controller/state machine ร่วม GUI และ CLI; ตั้งสถานะก่อน spawn worker
- recorder รับ stop_event/cancel_event; ใช้ monotonic clock; handle mic initialization error ด้วย finally
- ป้องกัน input ซ้อนตั้งแต่ recording ถึง verification; กำหนดชัดว่าจะ reject หรือ replace pending turn
- ใช้ cancellation checkpoint ก่อน model call, หลัง model response และก่อนทุก mutation
- แยก Finish recording กับ Cancel task; UI ตอบสนองทันทีและแสดงว่ารอ operation ปัจจุบันอยู่เมื่อจำเป็น
- เพิ่มเทสต์ double hotkey, double Send, text during recording/STT, cancel during STT/intent/agent, และ mic failure

เกณฑ์ผ่าน: 100 ชุด event burst จำลองไม่มี concurrent browser mutation; cancel แล้วไม่มี action ใหม่จากผลลัพธ์เก่า; Finish หยุด capture ภายในเป้าหมาย 150ms บนเครื่องทดสอบ

### PR 2 — Tab identity, Ownership และ Recovery (P0)

- แยก Browser.attach(target_id) กับ navigate(url); ยืมแท็บต้องไม่ navigate อัตโนมัติ
- ให้ผู้ใช้เลือกแท็บ/lock session เป็นทางเริ่มต้นที่แน่นอน หากต้องการตาม active tab จริงจึงพิจารณา extension ที่รายงาน browser tab identity
- เปรียบเทียบ parsed hostname/origin ตามกฎที่ชัดเจน ไม่ใช้ substring ทั้ง URL
- รองรับ tab closed, target detached, user switches tab และหลายหน้าต่าง โดยไม่แย่ง focus อย่างเงียบ ๆ
- track owns_target; close borrowed tab ต้อง detach เท่านั้น
- intent failure ต้องหยุดหรือคงหน้าปัจจุบัน ไม่ fallback ไปเว็บอื่น; replacement agent ต้องปล่อยทรัพยากรของตัวเก่า
- validate allowed URL schemes และ preserve explicit same-domain path navigation

เกณฑ์ผ่าน: in-page command บนหน้าที่มี unsaved form เกิด navigation 0 ครั้ง; เลือก target ถูกทุก deterministic fixture; shutdown ไม่ปิด borrowed tab; hostname ใน query string ไม่มีผลต่อการเลือกแท็บ

### PR 3 — Honest outcomes และ Trace (P1)

- เพิ่ม typed TurnResult พร้อม status, reason, evidence, actual_final_url, elapsed_ms, turn_id
- DONE เป็น completion claim ก่อน verifier; verifier ใช้ observable postconditions สำหรับงานที่รองรับ เช่น field value, URL, scroll offset, selected control และผลค้นหา
- งานที่ไม่มี verifier เพียงพอคืน unverified; ห้ามแสดง success เพียงเพราะโมเดลเลือก DONE
- budgets แยก wall time, model calls, mutations และ recovery attempts; ครบ budget คืน budget_exceeded
- บันทึก action attempt/result/uncertain outcome พร้อม unique ID; uncertain mutation ต้อง observe/reconcile ไม่ replay อัตโนมัติ
- reset per-turn text_calls/elapsed_ms ให้ครบ และแก้ callback ซ้ำ
- trace ไม่เก็บ raw audio โดย default; redact secrets/ข้อมูลอ่อนไหวใน export และจำกัดขนาด history

เกณฑ์ผ่าน: ทุก exit path มีสถานะชัดเจน; false-DONE fixture ไม่แสดง verified success; interrupted mutation ไม่ถูก replay; metrics ของ turn ใหม่ไม่รวม turn เก่า

### PR 4 — Latency instrumentation และ benchmark ก่อนเปลี่ยนโมเดล (P1)

บันทึก timestamp ด้วย monotonic clock: hotkey, recording_started, speech_end_estimated, endpoint_detected, stt_final, intent_ready, snapshot_ready, decision_ready, mutation_dispatched, effect_observed, outcome_verified

Metrics หลัก:

- time to UI feedback
- speech end → first verified visible effect
- speech end → verified task completion
- p50/p95 ของ endpoint/STT/intent/decision/browser/verification แยก cold และ warm
- task success, wrong-target rate, unwanted navigation, cancellation response, retries, model calls, cost per verified success

ชุดทดสอบตั้งต้น: 30 intent families × 3 รูปแบบการพูด (ไทย/อังกฤษ/ผสม) × 3 รอบ = 270 trials ต่อ configuration; ใช้ paired recordings และ randomized configuration order โดยรายงาน failure ด้วย

งานต้องมี click, text replacement, search+submit, dropdown, scroll, explicit navigation, follow-up turns, ambiguity, duplicate labels, dynamic rerender, slow network, provider error และ cancellation ให้ผล STT กับ downstream intent correctness แยกกัน เพราะ WER ต่ำไม่ได้รับประกันว่าคลิกถูก

ใช้ deterministic local fixtures สำหรับ correctness regression และ live sites จำนวนจำกัดสำหรับ latency/robustness; mock paid APIs ใน CI และแยก live benchmark ที่ผู้ใช้เลือกเรียกเอง

### PR 5 — ลดเวลา Voice Pipeline (P1)

- เพิ่ม push-to-talk ที่ปล่อยแล้ว finalize ทันที ก่อนลงทุนเปลี่ยน STT
- ทดลอง adaptive endpointing ช่วงประมาณ 300–600ms พร้อม pre-roll; ตรวจไม่ตัดคำไทย/ประโยคที่มีช่วงเว้นคิดก่อนเลือกระยะจริง
- abstraction ของ STT ต้องแยก batch กับ streaming capability; implementation ปัจจุบันเป็น batch แม้ชื่อโมเดลอาจมี capability อื่น
- streaming provider ต้องตรวจเอกสาร/endpoint/ภาษา/ราคาและ benchmark จริงก่อนเลือก ไม่มีข้อสรุปจาก review นี้ว่า Muse หรือ provider ใดเร็ว/แม่นที่สุด
- reuse HTTP connections; warm microphone/browser session เมื่อผู้ใช้เปิดใช้งาน; readiness check ก่อนรับคำสั่ง
- เพิ่ม per-stage deadline และ fallback ที่อธิบายได้; ไม่รอ timeout ยาวทุก turn แล้วค่อย fallback
- เตรียม snapshot แบบ read-only ขณะรับเสียงเมื่อทราบ targetId แล้วได้ แต่ต้อง revalidate ก่อน action เสมอ
- route คำสั่งที่เป็น unambiguous local control เช่น cancel/finish ไป deterministic handler; browser action shortcut ต้องอ้าง observed capability และผ่าน executor guard เดิม
- รักษา original transcript และ literal quoted text พร้อม normalized goal เพื่อลดการ rewrite ซ้ำระหว่าง intent และ text helper
- หากจะข้าม text helper สำหรับ literal text ต้องทำเป็นการเปลี่ยน contract/AGENTS.md อย่างเปิดเผย พร้อม test; baseline ปัจจุบันกำหนดให้ TYPE_TEXT เรียก text LLM
- speculative processing ของ partial transcript อนุญาตเพียงเตรียมงานที่ยกเลิกได้ ไม่ execute จาก transcript ที่ยังไม่ final

เป้าหมายเริ่มต้นบนเงื่อนไขทดสอบที่กำหนด: UI feedback p95 ≤100ms; manual endpoint p95 ≤150ms; simple in-page voice command speech-end→effect p50 ≤800ms และ p95 ≤1.5s ตัวเลขนี้ต้องปรับตาม baseline จริง ไม่ควรสัญญาว่า voice→browser ทุกคำสั่งต่ำกว่า 200ms

### PR 6 — Browser compatibility ตามหลักฐาน (P2)

ลำดับแนะนำ: constrained Enter/Escape/Tab และ submit → nested scroll/viewport-aware geometry → popup/new-tab lifecycle → open Shadow DOM → frames พร้อม frame/session identity → advanced widgets

เพิ่ม action ทุกชนิดผ่าน typed schema และ observed target เท่านั้น ไม่ให้ model สร้าง selector, JavaScript หรือ arbitrary key sequence ขึ้นเอง

ลด full-snapshot work หลังวัดผลแล้ว: scoped freshness checks, mutation-aware invalidation, omit invisible noise และ candidate prioritization แทนการตัด 250 actions แบบเงียบ ๆ ต้องแจ้ง truncation และมีทาง recovery เมื่อ target ไม่อยู่ในชุดที่ส่ง

ยังไม่เพิ่ม screenshot/VLM ในทุก step; ใช้เป็น bounded fallback เมื่อ DOM ไม่ครอบคลุมและมี benchmark รองรับ ส่วน canvas/drag-and-drop ให้ระบุว่า unsupported จนกว่าจะมี implementation และ test

### PR 7 — UX, Packaging และ Release (P2)

- UI แสดง Listening / Heard / Acting on [tab] / Verified result และเหตุผลที่หยุด; transcript แก้ได้และ re-run ได้โดยเริ่ม turn ใหม่
- microphone selector, level meter, push-to-talk/toggle setting, ไทย/อังกฤษ, ปุ่ม Cancel ที่ใช้ได้ตลอด และ compact overlay
- ไม่แสดงเครื่องหมายสำเร็จสีเขียวเมื่อ blocked/error/budget_exceeded/unverified
- health check สำหรับ mic, Chrome connection, provider credentials และ config โดยไม่เปิดเผย key
- แยก core กับ voice extras เพื่อลดภาระ scipy/audio/hotkey ของผู้ใช้ browser-only; แยก GUI/CLI optional imports
- config กลาง typed schema ใช้ env names/defaults สอดคล้องกัน; ไม่ให้ intent helper กับ field helper default คนละ provider โดยไม่ตั้งใจ
- README clone URL ของ fork, jev-gui/jev-voice setup, Windows prerequisites, capability matrix, troubleshooting และตัวอย่างหลาย turns
- CI lint, offline pytest, JS syntax, wheel build/install/import smoke; Windows voice checks และ Linux core checks; GUI/hardware integration มี platform-specific gate
- แก้ tests ที่ patch.start แล้วไม่ stop โดยใช้ context manager/fixture; เพิ่ม stateful session fakes ที่จำลอง ready→execution→done จริง

## Release gate

1. R01–R06 ปิดครบและมี regression coverage
2. 270-trial benchmark รายงานทุก failure และ p50/p95 แยกตามกลุ่มงาน; เป้าหมาย verified task success ≥95% ในขอบเขตที่ประกาศ
3. deterministic safety fixtures ไม่มี wrong-tab mutation, unexpected reload หรือ duplicate mutation; ไม่อ้าง zero-risk จาก sample เล็ก
4. cancel, provider timeout, network loss, microphone loss และ window shutdown ทิ้งระบบในสถานะที่เริ่ม turn ใหม่ได้
5. ตั้งค่าจากเครื่องใหม่ได้ตาม README และ CLI/GUI แสดง error ที่แก้ไขได้
6. benchmark ผูก commit hash, provider/model config, OS/browser version, network conditions และ timing boundary ชัดเจน

## สิ่งที่ยังไม่ควรทำเป็นงานแรก

ไม่ rewrite เป็น microservices; ไม่เปลี่ยน UI framework เพียงเพื่อหวังลด model latency; ไม่เลือกโมเดลจาก inference speed อย่างเดียว; ไม่เพิ่ม multimodal planner ทุก step; ไม่เพิ่ม site-specific scripts ใน generic policy และไม่ใช้ performance ของ Flights เดิมเป็นหลักฐานความเร็ว voice feature ใหม่

## ผลการตรวจในรอบรีวิวนี้

- Ruff: ผ่าน
- JavaScript syntax: `static/app.js` และ `snapshot.js` ผ่าน
- Build: สร้าง sdist และ wheel ผ่าน
- Core tests: 31 passed
- Voice tests: 11 passed เมื่อแทน sounddevice ด้วย mock เพื่อแยกจาก hardware; ไม่ถือเป็น microphone integration test
- Full suite ตามปกติยัง collect ไม่ผ่านในเครื่องรีวิว เพราะไม่มี PortAudio จึงไม่อ้างว่า full environment integration ผ่าน
- Setup แรกติด build evdev เพราะ environment กำหนด compiler ที่ไม่มี; ติดตั้งได้เมื่อใช้ CC=gcc และเพิ่ม socksio ใน review environment เพื่อรองรับ SOCKS proxy ของเครื่องนี้ ไม่ได้แก้ dependency files ของ repo
- Mocked reproduction ยืนยัน: URL ที่มี example.com อยู่ใน query ของคนละ hostname ถูกเลือกเป็น matching tab; close ปิด borrowed tab เมื่อใช้ default keep_open=False; intent timeout ของคำสั่ง “เลื่อนลง” คืน navigate ไป Google
- ไม่เรียก paid model APIs และไม่ทดสอบ live browser/microphone interaction; ไม่แก้ source, commit หรือ push

## Source map

- Agent: https://github.com/Bigthap/jev-ultrafast/blob/4ebed43fa98646366d9f72aa2cc3720f9a2472bd/jev_ultrafast/agent.py
- Browser: https://github.com/Bigthap/jev-ultrafast/blob/4ebed43fa98646366d9f72aa2cc3720f9a2472bd/jev_ultrafast/browser.py
- Voice: https://github.com/Bigthap/jev-ultrafast/blob/4ebed43fa98646366d9f72aa2cc3720f9a2472bd/jev_ultrafast/voice.py
- GUI: https://github.com/Bigthap/jev-ultrafast/blob/4ebed43fa98646366d9f72aa2cc3720f9a2472bd/jev_ultrafast/voice_gui.py
- Listener: https://github.com/Bigthap/jev-ultrafast/blob/4ebed43fa98646366d9f72aa2cc3720f9a2472bd/jev_ultrafast/voice_listener.py
- Model: https://github.com/Bigthap/jev-ultrafast/blob/4ebed43fa98646366d9f72aa2cc3720f9a2472bd/jev_ultrafast/model.py
- Existing evidence: https://github.com/Bigthap/jev-ultrafast/blob/4ebed43fa98646366d9f72aa2cc3720f9a2472bd/docs/performance.md
