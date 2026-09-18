# 单罐补加判定台

饮料车间配液罐实测糖度偏低时，计算**唯一补加剂量**并在可能溢罐时**明确阻断**的判定台。
React + TypeScript + Vite 前端与 Python 3.12 + FastAPI + Pydantic 后端真实联调。

## 判定规则

- 输入：当前体积 `V`、当前糖度 `C`、目标糖度 `T`、糖浆糖度 `S`、罐体容量 `K`
- 体积单位为毫升（mL），糖度为质量分数百分数（%），假定液体密度相同
- 仅当 `0 < C < T < S ≤ 100`、`V > 0`、`K > 0`、`V ≤ K` 且各输入**最多四位小数**时受理
- 按质量守恒计算唯一补加量：

  ```
  V·C + x·S = (V + x)·T   =>   x = V×(T-C)/(S-T)
  ```

- 容量判定 `V+x ≤ K` 以**精确有理数交叉相乘**完成（输入均为有限、至多
  四位小数的十进制数），整数部分再长也不舍去任何低位；对外数值仍以
  `decimal`（常规输入 50 位有效数字，输入更长时随整数位数自适应放大）呈现

- 以**未因展示格式改变的完整精度计算值**判定 `V + x ≤ K`：等于容量允许，超过容量禁止
- 放行时展示：公式代入、唯一补加量、终态体积、剩余容量与「允许补加」
- 容量不足时展示：超出量与「禁止补加」
- 展示数值最多保留四位小数（四舍五入）并去除无意义尾零；精确值非零但舍入后为 0
  （|值| < 0.00005）时显示 `<0.0001`，明确指示仍有微量，避免与「禁止补加」矛盾
- 空值、非有限数（NaN/∞）、精度超限或关系错误：HTTP 422 定位字段、整单拒绝，前端清除旧结论

## 腾容方案

判定为「禁止补加」时，操作员可在该结论下发起**生成腾容方案**，填写本次最多可排出的
当前料液量 `D`；系统复用原五项输入计算恢复补加所需的最小排出量，**不改写原判定**。

- 业务假设：排出的当前料液糖度仍为 `C`（罐内混合均匀）
- 反解最小排出量（判定比较全程精确有理运算，展示值以 decimal 呈现），
  使排出后补加的终态恰好顶到容量上限：

  ```
  (V-d)·C + (K-(V-d))·S = K·T   =>   d = V - K×(S-T)/(S-C)
  ```

- 排出后的糖浆剂量仍按原质量守恒公式 `x = (V-d)×(T-C)/(S-T)` 计算
- 以**完整精度**比较 `d` 与 `D`，只形成两种结果：
  - `d ≤ D` → **可执行**：展示 d、排出后体积、补加量与恰好不超过容量的终态
  - `d > D` → **超出排出上限**：展示仍缺少的排出量 `d-D`，不呈现可执行剂量
- `D` 为空、负数、精度超限或不小于 `V`：HTTP 422 定位 `D` 字段，
  前端清除旧方案但**保留原禁止结论**；请求失败也不会把腾容结果误作原始判定
- 「允许补加」结论下不出现腾容入口；若直接对允许补加的输入请求腾容
  （`d ≤ 0`，含终态恰等于容量的边界），HTTP 422 整单拒绝，不生成方案

## 稳健刻度方案

判定为「允许补加」时，操作员可在该结论下发起**生成稳健刻度方案**，填写单刻度量
`Q`、糖度波动 `U` 与终态容差 `E`；系统复用原五项输入，在固定刻度与糖度波动下
选择最稳健的刻度，**不改写原判定与腾容方案**。

- 现场泵按固定刻度投料：剂量为正整数 `n` 个刻度 `nQ`；糖浆实际糖度在
  区间 `[S-U, S+U]` 内波动
- 对剂量 `x` 与糖浆糖度 `s`，终态糖度为 `f(x, s) = (V·C + x·s)/(V + x)`；
  刻度 `n` 的最坏偏差为两个端点终态糖度偏离 `T` 的最大者：
  `W(n) = max(|f(nQ, S-U) - T|, |f(nQ, S+U) - T|)`
- 在 `V + nQ ≤ K` 的刻度中选择 `W` 最小者，**同值取较小 n**
- 算法**不逐刻度扫描**：从容量上界 `K-V`、
  两个端点命中 `T` 的 `A/(S∓U-T)` 与偏差分支相交处 `A/(S-T)`
  （`A = V×(T-C)`）推导实数断点，仅评估断点相邻整数及边界刻度；
  `W` 在相交处两侧分别严格下降、严格上升，故结果与穷举定义的全局最优一致
- 容量边界 `n_max = floor((K-V)/Q)`、断点相邻整数与 `W ≤ E` 判定均为
  **精确有理数运算**（整数部分超过 50 位也不会把低位舍掉而上舍出溢罐刻度）；
  对外数值以 `decimal`（常规输入 50 位有效数字，更长输入自适应放大）呈现
- 最优偏差 `≤ E` → **有稳健刻度**：展示剂量 `nQ`、终态糖度区间与最坏偏差
- 最优偏差 `> E` → **无稳健刻度**：展示最小容差缺口 `最优偏差-E`，不呈现剂量
- 容量放不下一个刻度（`V + Q > K`）→ 返回**业务结果**「容量放不下一个刻度」，
  不按字段错误拒绝
- `Q ≤ 0`、`U < 0`、`S-U ≤ T`、`S+U > 100` 或 `E < 0`：HTTP 422 按
  Q、U、E 顺序返回全部字段错误，前端清除旧方案但**保留原允许结论**
- 「禁止补加」结论下不出现稳健刻度入口；失败或重新判定都会清除旧方案

## 目录结构

```
├── docker-compose.yml      # web / api / verify 三个服务
├── api/                    # FastAPI 后端（Python 3.12）
│   ├── app/                #   schemas.py(校验) service.py(判定) main.py(路由)
│   └── tests/              #   pytest：放行、溢罐、非法输入主线
├── web/                    # React + TS + Vite 前端
│   ├── src/lib/            #   format(展示格式化) api(请求) view(视图模型) state(状态机)
│   ├── tests/              #   Vitest：格式化、视图模型、状态机、结论面板
│   └── nginx.conf          #   静态托管 + /api 反向代理
└── verify/                 # 一次性验收服务（pytest + httpx + Playwright）
    └── tests/              #   API 网络验收 + 真实浏览器端到端
```

## 启动（Docker Compose）

```bash
WEB_PORT=8080 API_PORT=8000 docker compose up -d --build api web
# 打开 http://localhost:8080
```

宿主端口可用环境变量指定；不设置时默认 ephemeral（Docker 自动分配空闲端口，
可用 `docker compose port web 80` 查看），避免与本机已占用端口冲突。
`verify` 验收服务只走 compose 内部网络，不依赖任何宿主端口。

```bash
WEB_PORT=9000 API_PORT=9001 docker compose up -d --build api web
```

## 一次性验收

`verify` 服务依赖 `api`、`web` 健康检查通过后，对运行中的服务执行
API 网络验收（httpx）与真实浏览器端到端（Playwright/Chromium），跑完即退出：

```bash
docker compose up --build --exit-code-from verify verify
# 退出码即验收结果；结束后清理：
docker compose down
```

## 本地开发

```bash
# 后端（Python 3.12）
cd api
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000

# 前端（Node 20+），开发服务器把 /api 代理到 API_PORT（默认 8000）
cd web
npm ci
npm run dev        # http://localhost:5173
```

## 测试

```bash
cd api && python -m pytest tests/ -v     # 后端：84 例
cd web && npm test                       # 前端：57 例
# 端到端：先启动 api 与 web，再执行 verify 套件
cd verify && pip install -r requirements.txt
WEB_BASE_URL=http://localhost:5173 API_BASE_URL=http://localhost:8000 python -m pytest tests -v
```

全部测试均驱动真实应用与真实计算，不使用假数据或固定响应。

## API 请求示例

```bash
curl -X POST http://localhost:8000/api/judge \
  -H 'Content-Type: application/json' \
  -d '{"V":"500","C":"5","T":"8","S":"30","K":"600"}'
```

放行响应（数值为完整精度十进制字符串，展示格式化由前端负责）：

```json
{
  "verdict": "ALLOWED",
  "message": "允许补加",
  "dose": "68.181818181818181818181818181818181818181818181818",
  "finalVolume": "568.18181818181818181818181818181818181818181818182",
  "remainingCapacity": "31.81818181818181818181818181818181818181818181818",
  "excess": null,
  "inputs": {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"}
}
```

溢罐（`K` 改为 `"550"`）：`verdict` 为 `FORBIDDEN`、`message` 为「禁止补加」，
`excess` 给出超出量、`remainingCapacity` 为 `null`。

非法输入（如 `T` 不大于 `C`）：HTTP 422，整单拒绝并定位字段——

```json
{
  "detail": "输入校验失败，已整单拒绝",
  "errors": [{"field": "T", "message": "目标糖度 T 必须大于当前糖度 C"}]
}
```

## 腾容方案 API 示例

```bash
curl -X POST http://localhost:8000/api/drain-plan \
  -H 'Content-Type: application/json' \
  -d '{"V":"500","C":"5","T":"8","S":"30","K":"550","D":"20"}'
```

可执行响应（终态恰好顶到容量上限 550，数值为完整精度十进制字符串）：

```json
{
  "status": "EXECUTABLE",
  "message": "可执行",
  "minDrain": "16",
  "volumeAfterDrain": "484",
  "dose": "66",
  "finalVolume": "550",
  "shortfall": null,
  "inputs": {"V": "500", "C": "5", "T": "8", "S": "30", "K": "550", "D": "20"}
}
```

排出上限不足（`D` 改为 `"10"`）：`status` 为 `EXCEEDS_LIMIT`、`message` 为「超出排出上限」，
`shortfall` 给出仍缺少的排出量 `6`，`dose`、`volumeAfterDrain`、`finalVolume` 均为 `null`。

## 稳健刻度方案 API 示例

```bash
curl -X POST http://localhost:8000/api/robust-plan \
  -H 'Content-Type: application/json' \
  -d '{"V":"500","C":"5","T":"8","S":"30","K":"600","Q":"10","U":"2","E":"1"}'
```

有稳健刻度响应（最优刻度 n=7，数值为完整精度十进制字符串）：

```json
{
  "status": "ROBUST",
  "message": "有稳健刻度",
  "n": 7,
  "dose": "70",
  "finalSugarLow": "7.8245614035087719298245614035087719298245614035088",
  "finalSugarHigh": "8.3157894736842105263157894736842105263157894736842",
  "worstDeviation": "0.3157894736842105263157894736842105263157894736842",
  "toleranceGap": null,
  "inputs": {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600", "Q": "10", "U": "2", "E": "1"}
}
```

最优偏差超出容差（`E` 改为 `"0.1"`）：`status` 为 `NO_ROBUST_SCALE`、`message` 为
「无稳健刻度」，`toleranceGap` 给出最小容差缺口，`n`、`dose`、`finalSugarLow`、
`finalSugarHigh`、`worstDeviation` 均为 `null`。
容量放不下一个刻度（如 `Q` 改为 `"1000"`）：`status` 为 `CAPACITY_INSUFFICIENT`、
`message` 为「容量放不下一个刻度」，数值字段均为 `null`。
