# 数字人合成走 ffmpeg 后期叠加，而不是把 `<video>` 写进渲染 DOM

成片由 headless Chrome 抓 DOM+GSAP 时间轴渲染而成，目前整份合成里没有任何 `<video>` 元素。
我们决定：先照原样渲染 PPT 成片，再用 ffmpeg 把各帧的数字人片段按帧绝对起点叠加到左上角，
而不是在每帧 HTML 里嵌入 `<video>` 让浏览器连人一起抓。

## Considered Options

- **DOM 内嵌 `<video>`**：唯一优势是 `hyperframes preview` 预览时能直接看到数字人。
  代价是要在 hyperframes 里新建一条 media track 并协调 `data-track-index`，
  且把逐帧精确性押在 `chrome-headless-shell` 的解码能力与视频元素寻址行为上。
- **ffmpeg 后期叠加（选中）**：确定性、与浏览器编解码能力解耦、不动 hyperframes 的轨道模型；
  项目本来就在用 ffmpeg（BGM 循环、音频转码），加一步 overlay 是顺势而为。

## Consequences

- 预览（`hyperframes preview`）里看不到数字人，只有在成片里才有。这是本决策明确接受的代价。
- 帧的绝对起始时间必须由 `assemble.build` 的累加结果单独暴露给合成步骤，叠加才能和字幕、音频同一时钟。
- 数字人片段必须被精确裁剪/补齐到帧总时长，否则误差会逐帧累积成可见的漂移。
