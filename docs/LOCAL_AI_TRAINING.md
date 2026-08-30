# Local AI Training v2（实验分支）

> 分支：`feat/local-ai-training-v2`
>
> 这套代码只负责本地训练实验，不会改变 `main` 的 Easy / Medium / Hard 默认 PvE，也不会把模型权重、训练数据或 PyTorch 依赖带进普通游戏安装。

## 0. 架构与安全边界

训练模型不是一个“任意走子生成器”。规则权威始终是现有 `FiveDEngine`：

```text
canonical multiverse state
        ↓
ActionPlanner.search()
        ↓
完整合法 AIActionPlan candidates
        ↓
StateEncoder + ActionEncoder
        ↓
Policy logits（只在当前 candidates 内） + Value
        ↓
选择一个 candidate
        ↓
apply_action_plan()
        ↓
逐 Move 精确重解析 + execute_action_move() + 单次 submit_action()
```

因此神经网络不会绕过 `Action / The Present / RoyalRules` 自己构造 source/destination。

训练代码位于 `src/training/`；主游戏代码不顶层 import Torch。

## 1. 下载训练分支

### Git 方法（推荐）

```powershell
git clone https://github.com/Polarzen/5Dchess.git
cd 5Dchess
git fetch origin
git switch feat/local-ai-training-v2
git pull
```

确认：

```powershell
git branch --show-current
git log -1 --oneline
```

第一行必须是：

```text
feat/local-ai-training-v2
```

### GitHub Download ZIP

在 GitHub 仓库页面先把左上角 branch selector 切换到 `feat/local-ai-training-v2`，再选择 **Code → Download ZIP**。解压后确认存在：

```text
src/training/
scripts/training/
requirements-training.txt
```

如果没有这些目录，说明下载的是 `main`，不是训练分支。

## 2. Python 3.11 与训练虚拟环境

推荐 Windows 10/11 + Python 3.11。

最简单：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\setup_training.ps1
```

脚本创建：

```text
.venv-training\
```

并安装普通项目依赖。

训练环境与普通游戏环境分离。

### 手工创建

```powershell
py -3.11 -m venv .venv-training
.\.venv-training\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 3. PyTorch：CPU 与 NVIDIA CUDA

不要根据仓库文档猜 CUDA wheel。

### 先检查 NVIDIA 驱动

```powershell
nvidia-smi
```

如果有 NVIDIA GPU，请访问 PyTorch 官方安装 selector：

```text
https://pytorch.org/get-started/locally/
```

选择：

- OS: Windows
- Package: Pip
- Language: Python
- Compute Platform: 与当前 PyTorch 官方支持及你的驱动相匹配的 CUDA build

然后在 `.venv-training` 中执行 selector 给出的命令。

完成后：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\setup_training.ps1 -TorchMode existing
```

脚本不会覆盖一个已经可 import 的 CUDA Torch。

### 纯 CPU

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\setup_training.ps1 -TorchMode cpu
```

该模式显式使用 PyTorch 官方 CPU wheel index。

### `-TorchMode auto`

默认行为：

- 已存在可用 Torch → 保留。
- 未安装 Torch且检测到 `nvidia-smi` → **不会猜 CUDA 版本**，停止并提示使用官方 selector。
- 未检测到 NVIDIA 工具 → 安装官方 CPU Torch。

## 4. 检查训练设备

```powershell
.\.venv-training\Scripts\python.exe .\scripts\training\check_device.py --device auto
```

输出包括：

- Python version
- Torch version
- `cuda_available`
- Torch CUDA runtime version
- GPU name
- GPU VRAM（Torch 能读取时）
- 实际选择的 `cpu` / `cuda`

`--device auto`：CUDA 可用时选择 CUDA，否则 CPU。

显式要求 CUDA：

```powershell
.\.venv-training\Scripts\python.exe .\scripts\training\check_device.py --device cuda
```

如果 Torch 不能使用 CUDA，会 fail closed，而不是偷偷退回 CPU。

## 5. 第一次必须先跑 smoke

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\smoke_training.ps1 -Device cpu
```

或：

```powershell
.\.venv-training\Scripts\python.exe -m src.training.smoke --device cpu
```

Smoke 自动执行：

```text
2 局 tiny canonical self-play
    ↓
NPZ shard dataset
    ↓
2 epoch tiny Policy/Value training
    ↓
safetensors checkpoint
    ↓
重新实例化 + reload
    ↓
相同 sample logits/value 一致性检查
    ↓
2 局 tiny Arena
```

它的目标只是证明闭环可执行，不代表模型已经有棋力。

如果 CPU smoke 能通过，再开始正式生成数据。

## 6. 训练表示

### State Encoding v1

每个 sample 使用 bounded multiverse representation：

```text
state_boards   [MAX_RELEVANT_BOARDS, 12, 8, 8]
board_meta     [MAX_RELEVANT_BOARDS, 12]
board_mask     [MAX_RELEVANT_BOARDS]
state_global   [16]
```

默认：

```text
MAX_RELEVANT_BOARDS = 16
```

12 个棋盘通道是 White/Black × K/Q/R/B/N/P。

Board metadata 保留：

- signed Timeline L（正负号不会丢失）
- canonical turn
- side
- active
- playable / historical
- required
- movable
- Present
- timeline owner
- legacy half-move time 的 bounded hint

优先选择 playable/frontier board，再补当前 Present 和最新 historical context；不会把所有历史 Board 当作独立当前子力重复累计。

### Action Encoding v1

每一个候选是完整 `AIActionPlan`：

```text
action_moves      [candidate, MAX_MOVES_PER_ACTION, 40]
action_move_mask  [candidate, MAX_MOVES_PER_ACTION]
action_global     [candidate, 4]
candidate_mask    [candidate]
```

默认：

```text
MAX_MOVES_PER_ACTION = 32
```

每步编码：

- source / destination x/y
- source / destination signed timeline
- canonical turn / side
- dx/dy/dt/dl
- mover color/type
- capture type
- promotion
- castling
- en-passant
- branching
- cross-timeline
- created timeline（执行 clone 上可获得时）

超过上限不会静默截断，会直接失败。

## 7. 第一批 self-play 数据

建议第一次只生成 50–100 局：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\generate_selfplay.ps1 `
    -Games 100 `
    -Teacher mixed `
    -Output datasets\selfplay-001 `
    -Seed 42
```

对应 Python：

```powershell
.\.venv-training\Scripts\python.exe -m src.training.selfplay `
    --games 100 `
    --teacher mixed `
    --output datasets\selfplay-001 `
    --seed 42 `
    --max-actions 200
```

Teacher：

```text
easy    随机选择完整合法 Action
medium  对完整 Action submit 后的状态进行 canonical multiverse evaluation
hard    再考虑一层 opponent complete Action response
mixed   50% easy / 40% medium / 10% hard
```

所有候选先由 `ActionPlanner` 产生。

### 可复现模式

要去掉 wall-clock planner cutoff，仅使用 states/actions/moves 数量预算：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\generate_selfplay.ps1 `
    -Games 20 `
    -Teacher easy `
    -Output datasets\deterministic-001 `
    -Seed 42 `
    -DeterministicPlanner
```

这个模式最适合做复现实验；正式大量数据可继续使用 wall-clock 上限控制耗时。

## 8. Dataset v1

输出：

```text
datasets/selfplay-001/
├── metadata.json
├── shard_000000.npz
├── shard_000001.npz
└── ...
```

没有 pickle dataset。

`metadata.json` 保存：

- dataset schema version
- state/action encoder version
- engine baseline SHA
- generator config
- seed
- game/sample count
- shard index

NPZ 只保存 numeric/string NumPy arrays，并以 `allow_pickle=False` 读取。

Candidate 数量在每个 sample 中可以不同；DataLoader 在 batch 内按本 batch 最大 candidate 数 padding，并使用 mask 排除 padding。

Dataset reader 只缓存当前 shard，不要求把未来几十 GB 数据整体加载进 RAM。

### Ctrl+C

普通 Ctrl+C 会进入 writer cleanup；已经完成的 shard 会保留为完整可读文件。

要继续向同一 dataset 追加：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\generate_selfplay.ps1 `
    -Games 50 `
    -Teacher mixed `
    -Output datasets\selfplay-001 `
    -Seed 42 `
    -Resume
```

如果不传 `-Resume`，对已有 dataset 路径会拒绝覆盖。

## 9. 开始 small 模型训练

第一次推荐：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\train_local.ps1 `
    -Dataset datasets\selfplay-001 `
    -Run runs\run-001 `
    -Epochs 50 `
    -BatchSize 64 `
    -Device auto `
    -Preset small
```

CPU 也可：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\train_local.ps1 `
    -Dataset datasets\selfplay-001 `
    -Run runs\run-001 `
    -Epochs 20 `
    -BatchSize 32 `
    -Device cpu `
    -Preset small
```

模型 preset：

```text
tiny    CI / smoke only
small   默认；普通 CPU / 低显存 GPU
medium  更宽；建议 8 GB+ NVIDIA GPU 再尝试
```

实际参数量会在训练启动时打印，不依赖文档中的估算值。

## 10. 模型结构

```text
12-channel board
    ↓ shared 2-layer CNN
board metadata MLP
    ↓
masked mean + max across relevant boards
    + global state features
    ↓
State embedding

完整 candidate Move sequence
    ↓ shared Move MLP
masked mean + max across Action moves
    + Action global flags
    ↓
Action embedding

State embedding + each Action embedding
    ↓
Policy scorer → N legal candidate logits

State embedding
    ↓
Value head → tanh[-1, 1]
```

Policy padding candidate 在 logits 中被 mask 成不可选。

## 11. Loss 与日志

训练输出每 epoch：

- policy cross entropy
- value Huber loss
- total loss
- policy top-1 accuracy
- samples/sec
- learning rate
- elapsed time

日志：

```text
runs/run-001/history.jsonl
```

默认 train/validation split 为 95/5。

因 `max_actions` / planner budget 截断的 episode 不伪造 win/loss；其 sample 默认 `value_mask=false`，仍可训练 teacher policy，但不会进入监督 value loss。

## 12. Checkpoint

```text
runs/run-001/
├── history.jsonl
├── best/
│   ├── model.safetensors
│   ├── metadata.json
│   └── resume_state.pt
└── last/
    ├── model.safetensors
    ├── metadata.json
    └── resume_state.pt
```

`model.safetensors`：推理模型权重。

`metadata.json`：

- checkpoint version
- encoder versions
- dataset schema version
- engine baseline SHA
- model config
- epoch/global step
- seed
- best validation loss
- training config

版本不一致会 fail closed。

`resume_state.pt` 只保存 optimizer/scheduler 的**本项目本地可信断点**。它使用 Torch pickle 序列化；不要从陌生来源下载并加载 `resume_state.pt`。

## 13. 中断与断点续训

训练时按 Ctrl+C 可以停止进程；最近一次 `last` checkpoint 保留在上一次完成的保存点。

继续到总 epoch 100：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\resume_training.ps1 `
    -Dataset datasets\selfplay-001 `
    -Run runs\run-001 `
    -Checkpoint runs\run-001\last `
    -Epochs 100 `
    -Device auto
```

`-Epochs 100` 表示目标总 epoch，不是额外再跑 100 个。

Resume 会恢复：

- model
- optimizer
- scheduler
- epoch
- global step

## 14. Arena

对 Easy：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\arena.ps1 `
    -Checkpoint runs\run-001\best `
    -Opponent easy `
    -Games 20 `
    -Device auto
```

对 Medium：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\arena.ps1 `
    -Checkpoint runs\run-001\best `
    -Opponent medium `
    -Games 20 `
    -Device auto
```

再尝试 Hard：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\arena.ps1 `
    -Checkpoint runs\run-001\best `
    -Opponent hard `
    -Games 20 `
    -Device auto
```

Arena 自动交换 White / Black，报告：

- W/D/L
- win rate / draw rate
- average actions
- illegal Action count
- stale plan failure count
- budget termination count
- average neural inference ms

`illegal_action_count` 正常必须为 0；非 0 时 CLI 返回失败，不会偷偷忽略。

## 15. 如何逐步扩大训练

不要第一次就生成几万局。

推荐：

```text
阶段 A
50–100 games
small
20–50 epochs
先验证 loss / checkpoint / Arena

阶段 B
500–2,000 games
small
增加 mixed teacher 数据
比较多个 seed 的 Arena

阶段 C
更多 shard
small 或 medium
保留固定验证 dataset
定期 Arena vs Easy/Medium/Hard
```

只有闭环稳定后再考虑 MCTS、自博弈迭代或更大的网络。

## 16. 磁盘与 Git

以下默认被 `.gitignore` 排除：

```text
datasets/
training_data/
data/training/
checkpoints/
runs/
*.pt
*.pth
*.safetensors
.venv-training/
```

不要用 Git LFS 上传训练权重或大数据。

生成大量数据前查看磁盘：

```powershell
Get-PSDrive -PSProvider FileSystem
```

## 17. 备份

建议只备份：

```text
runs/run-001/best/
runs/run-001/last/
runs/run-001/history.jsonl
datasets/selfplay-001/metadata.json
```

以及你希望长期保留的 dataset shards。

可复制到独立磁盘，例如：

```powershell
Copy-Item runs\run-001 D:\5dchess-backups\run-001 -Recurse
```

不要依赖 GitHub 作为 checkpoint 存储。

## 18. 常见 Windows 问题

### PowerShell 禁止脚本

当前窗口临时允许：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

或每次使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\training\smoke_training.ps1
```

### `torch.cuda.is_available() == False`

检查：

```powershell
nvidia-smi
.\.venv-training\Scripts\python.exe -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

如果 Torch 显示 `+cpu`，说明装的是 CPU build。重新使用 PyTorch 官方 selector 安装 CUDA build，不要只安装系统 CUDA Toolkit 就假设 Python Torch 自动变成 CUDA build。

### CUDA OOM

按顺序尝试：

1. `-BatchSize 64` → `32` → `16`
2. `medium` → `small`
3. 关闭其他 GPU 程序
4. 再考虑 CPU

不要为了避免 OOM 修改 encoder mask 或非法截断 Action。

### Windows DataLoader 卡住

默认：

```text
NumWorkers = 0
```

这是为了 Windows `spawn` 可靠性。确认稳定后可尝试提高。

### 路径含空格

PowerShell wrapper 以单独参数传递路径；优先用 wrapper，不要手工拼接未加引号的 Python command。

## 19. 当前限制

Local AI Training v2 第一版故意不包含：

- MCTS
- 大型 Transformer / GNN
- 分布式训练
- 云端长训
- 在线模型下载
- Hugging Face pretrained model
- 自动把 Neural AI 接进 Web Easy/Medium/Hard

目标是先得到正确、可复现、可断点续训的 canonical Action training pipeline。
