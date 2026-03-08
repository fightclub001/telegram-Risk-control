# 部署说明（含 Railway 持久化）

## 在 Railway 中挂载 Volume（让配置与数据在重新部署后不丢失）

本机器人把配置、举报记录、违规记录、媒体权限统计等写入 **`/data` 目录**。若未挂载持久化卷，每次重新部署后该目录会被清空，你添加的关键词等配置会丢失。

### 方法一：在 Railway 网页里操作

1. 打开 [Railway Dashboard](https://railway.app/dashboard)，进入你的项目。
2. 选中运行本机器人的 **Service**（服务）。
3. 在画布空白处 **按 `Ctrl+K`（Windows）或 `Cmd+K`（Mac）** 打开 Command Palette，或 **右键点击画布**。
4. 选择 **「Add Volume」** 或 **「Create Volume」**。
5. 在提示选择要挂载到的服务时，选当前这个机器人服务。
6. 配置 **Mount Path（挂载路径）**：
   - 填 **`/data`**（与代码里默认的 `DATA_DIR` 一致）。
   - 若你在环境变量里设置了 `DATA_DIR=/别的路径`，则这里填 **与 `DATA_DIR` 相同的路径**。
7. 保存/创建后，重新部署一次服务。之后 `/data` 下的文件会保存在 Volume 上，重新部署也不会清空。

### 方法二：用 Railway CLI

在项目目录执行：

```bash
# 先 link 到当前项目（若未 link 过）
railway link

# 为当前服务添加 Volume，挂载到 /data
railway volume add --mount-path /data
```

部署时该 Volume 会挂载到容器的 `/data`，与代码中默认的 `DATA_DIR` 一致。

### 可选：自定义数据目录

若你希望把数据存到别的路径（例如 `/app/data`），在 Railway 的 **Variables** 里添加：

- 变量名：`DATA_DIR`
- 值：`/app/data`（或你实际挂载 Volume 的路径）

然后把 Volume 的 **Mount Path** 设为同一路径（如 `/app/data`）。

---

## 环境变量

部署时请设置：

- `BOT_TOKEN`：机器人 Token
- `GROUP_IDS`：监控的群 ID，空格分隔，如 `-1001234567890 -1009876543210`
- `ADMIN_IDS`：管理员 Telegram 用户 ID，空格分隔
- （可选）`DATA_DIR`：数据目录，默认 `/data`，需与 Volume 挂载路径一致

## 媒体权限与助力

- 发媒体权限：合规消息满 50 条 / Telegram 会员 / 为群组助力 4 次（满足其一即可）。
- 「助力」次数需管理员在群内**回复该用户任意一条消息**后发送：`/setboost 4`（数字可改），即把该用户在本群的助力次数设为 4，用于解锁发媒体。
