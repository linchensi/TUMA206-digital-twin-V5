# TUMA206 Beverage Digital Twin — Demo Script / 演示讲稿

> Bilingual run-sheet. **Bold English lines** = what you say out loud. 中文 = 操作提示 / 备注。
> 架构要点：**云端只放 dashboard（只显示 + 下发命令），本地跑真正的产线仿真与控制，两者通过 MQTT 通信，故障自动推送到 Telegram。** 这正是老师要的 ISA-95 / Purdue 分层。

---

## 0. Pre-demo setup / 演示前准备（提前 5 分钟做好）

1. 电脑联网（连得上 HiveMQ Cloud 8883）。
2. 终端启动**本地后端**（这是"工厂现场"那一半）：
   ```powershell
   python local_backend.py
   ```
   看到 `[OK] Connected via MqttBus` 和 `Telegram alarms: on`，手机会收到一条 `backend online`。
3. 浏览器打开**云端 dashboard**（Streamlit Cloud 部署的那个，`DASHBOARD_MODE=remote`）。
4. 手机打开 Telegram，停在 `tumagroup1_bot` 的对话界面，投屏/可见。
5. ALARMS 页侧边栏填好 OpenAI key（或留空走 rule-based）。

> 备用方案：如果现场网络不稳，可在本机同时跑后端 + `DASHBOARD_MODE=remote streamlit run dashboard/app.py`，效果一样。

---

## 1. Opening / 开场（30 秒）

> **"This is a digital twin of a beverage pasteurization and bottling line. It follows the ISA-95 layering: the plant simulation and PLC control run locally — the factory floor — while this dashboard runs in the cloud as a display-and-command station only. The two talk over MQTT, and any alarm is pushed to our operators on Telegram."**

中文补充：左边终端 = 本地产线（M1 仿真 + M2 PLC + M3 历史库），云端网页 = M4 dashboard，AI = M5。Dashboard 不直接控制机器，所有动作都是 MQTT 命令。

---

## 2. Start the line over MQTT / 远程启动（1 分钟）

操作：在云端 dashboard 的 SCHEMATIC 页点 **START**。

> **"When I press START in the cloud, it doesn't touch the machine directly — it publishes an MQTT command. The local backend receives it, runs the real start-up sequence, and streams the live tags back up to this screen."**

中文：指给观众看终端里 PLC 状态从 IDLE → STARTING → RUNNING，云端 P&ID 同步亮起：进料泵转动、管道蓝色流动、巴氏杀菌加热条跳动、灌装喷嘴出流、传送带瓶子移动。

> **"Notice the round-trip: command goes down over MQTT, data comes back up. The dashboard is a pure window into the plant."**

---

## 3. Normal operation & trends / 正常运行与趋势（45 秒）

操作：切到 **TRENDS** 页。

> **"Here are the live process trends — tank level holding around its setpoint, pasteurizer at 72 degrees, cooler pulling product down to 25. All of this is flowing from the local plant through MQTT."**

中文：演示 **FREEZE** 一个图（继续累积但画面冻结，可缩放），再 **UNFREEZE** 追上实时。

---

## 4. Fault → Alarm → AI → Telegram / 故障联动（核心亮点，2 分钟）

操作：回 SCHEMATIC，选 **"Temperature excursion"（温度超限）** → **INJECT**。

> **"Now I inject a process fault from the dashboard — again, just an MQTT command. Watch three things happen at once."**

1. **云端**：巴氏温度爬升（P&ID 边框转红），约 10 秒后 `TEMP_OUT_OF_RANGE` 报警，产线进入 FAULT。
2. **AI（ALARMS 页）**：自动诊断面板弹出 —
   > **"The AI assistant immediately diagnoses the alarm and recommends an action — here, divert or quarantine the product."**
3. **手机 Telegram**：举起手机/切投屏 —
   > **"And at the same moment, the alarm is pushed to Telegram — so an operator who isn't watching the screen still gets paged on their phone."**

中文：这一步把 MQTT（数据链）+ AI（M5 诊断）+ Telegram（L4 企业通报）三者串起来，是整个 demo 的高潮。

操作：点 **RESET** → 温度回落，报警**自动清除**，产线自动恢复。
> **"I reset the fault — the temperature recovers, the alarm auto-clears, and the line resumes on its own."**

---

## 5. (Optional) more fault types / 备选故障（按时间取舍）

- **Sensor（L1）**：`Temperature sensor stuck` → `SENSOR_TEMP_STUCK`，AI 提示别信温度联锁。
- **Equipment（L2）**：`Feed pump failure` → `PUMP_NO_FLOW`，AI 提示查电机/联轴器/堵塞。
- **Infrastructure（L4）**：`Data link stale` → dashboard 冻结显示 "DATA LINK FROZEN"，演示数据链中断时画面如何安全冻结。
- **Manual override**：把 Cooler 拖到 5% → `COOLER_HIGH`；或 Inlet 100% + Feed 0% → 灌满 → `TANK_OVERFLOW`。

> 每个故障都会同时触发对应的 Telegram 通报，可挑 1-2 个展示。

---

## 6. AI consultation / AI 问答（45 秒）

操作：ALARMS 页用快捷按钮或自定义提问。
> **"Beyond diagnosis, the assistant is interactive. I can ask: 'What happens if I raise the pump speed to 90 percent?' and it answers using the current process state."**

---

## 7. Closing / 收尾（30 秒）

> **"To summarize: a locally-controlled plant, a cloud dashboard that only observes and commands, MQTT as the industrial data link, AI for diagnosis, and Telegram for enterprise alerting. It's a small but complete ISA-95 stack."**

中文：强调"符合老师要求"——云端只做 dashboard、控制在本地、用 MQTT、dashboard 不直接控机器、加了 Telegram 通报。

---

## Q&A 备答 / Likely questions

- **"How does the cloud control the plant safely?"** — 它从不直接控机器；只在 `btl/cmd` 上发命令，由本地 PLC 决定执行，本地保留所有联锁与安全逻辑。
- **"What broker?"** — HiveMQ Cloud（免费 serverless），TLS 8883，账号密码认证；topic 前缀隔离各组。
- **"Is the AI making control decisions?"** — 不。AI 只做诊断与建议（M5），控制由确定性的 PLC 状态机做（M2）。
- **"What if MQTT drops?"** — 注入 `Data link stale` 演示：dashboard 冻结在最后已知值并报 DATA_STALE，不会显示假数据。
