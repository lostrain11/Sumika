// Fixed passive collector: no seeking, track enablement, fetch or page commands.
(config) => {
  if (location.origin !== config.origin) return {ok:false, reason:'origin_changed'};
  const visible = element => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 &&
      rect.top < innerHeight && rect.left < innerWidth && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const videos = [...document.querySelectorAll('video')].filter(visible);
  if (videos.length !== 1) return {ok:false, reason:videos.length ? 'ambiguous_video' : 'visible_video_missing'};
  const video = videos[0];
  if (!Number.isFinite(video.currentTime)) return {ok:false, reason:'media_time_unavailable'};
  // Passive bookkeeping survives between snapshots. Even a tiny seek completed
  // between polls must fence old context; wall-clock heuristics cannot prove it.
  const monitorKey = Symbol.for('sumika.companion.videoTimeline.v1');
  if (!globalThis[monitorKey]) Object.defineProperty(globalThis, monitorKey,
    {value:{videos:new WeakMap(), nextInstance:1}});
  const monitor = globalThis[monitorKey];
  let timeline = monitor.videos.get(video);
  if (!timeline) {
    timeline = {instance:monitor.nextInstance++, revision:0};
    monitor.videos.set(video, timeline);
    video.addEventListener('seeking', () => {timeline.revision++;});
    video.addEventListener('emptied', () => {timeline.revision++;});
  }
  const page = new URL(location.href);
  const bilibili = location.hostname === 'www.bilibili.com' || location.hostname === 'bilibili.com';
  const rawPart = bilibili ? page.searchParams.get('p') : null;
  const part = rawPart && /^[1-9][0-9]{0,5}$/.test(rawPart) ? Number(rawPart) : 1;
  const url = location.origin + location.pathname + (bilibili && part > 1 ? `?p=${part}` : '');
  // Local change fingerprint only; never expose a signed media URL/query.
  let sourceFingerprint = 2166136261;
  for (const char of video.currentSrc) {
    sourceFingerprint = Math.imul(sourceFingerprint ^ char.charCodeAt(0), 16777619) >>> 0;
  }
  const media_identity = {url, document_started_at:performance.timeOrigin,
    source_fingerprint:sourceFingerprint.toString(16),
    media_instance:timeline.instance, timeline_revision:timeline.revision,
    ...(bilibili ? {part} : {})};
  if (video.seeking) return {ok:true,url,title:document.title.slice(0,512),
    observed_at:new Date().toISOString(),media_time_seconds:video.currentTime,
    media_identity, paused:video.paused,ended:video.ended,ready_state:video.readyState,
    seeking:true,subtitles:'',image:null,frame_status:'seeking',cues:[],valid:false,reason:'video_seeking'};
  const tracks = [...video.textTracks].filter(track =>
    ['subtitles','captions'].includes(track.kind) && track.mode !== 'disabled');
  const cues = tracks.flatMap(track => [...(track.activeCues || [])].filter(cue =>
    typeof cue.text === 'string' && cue.startTime <= video.currentTime && video.currentTime < cue.endTime)
    .slice(0, 32).map(cue => {
      const fragment = cue.getCueAsHTML();
      return {start:cue.startTime, end:cue.endTime, text:(fragment.textContent || '').slice(0,12000),
        language:track.language, label:track.label.slice(0,256)};
    })).slice(0,32);
  let image = null, frame_status = 'not_requested';
  if (config.capture_frame === true) {
    if (video.readyState < 2 || !video.videoWidth || !video.videoHeight) {
      frame_status = 'video_frame_unavailable';
    } else {
      try {
        // Drawing only the media element excludes sibling DOM overlays such
        // as Bilibili danmaku, controls and comments. Never draw the page.
        const scale = Math.min(1, 960 / video.videoWidth, 540 / video.videoHeight);
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
        canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
        const data = canvas.toDataURL('image/jpeg', 0.85).split(',')[1];
        if (data.length <= 400000) {
          image = {media_type:'image/jpeg', data_base64:data};
          frame_status = 'video_element_available';
        } else frame_status = 'video_frame_over_budget';
      } catch (_) {frame_status = 'video_frame_unreadable';}
    }
  }
  const subtitles = [...new Set(cues.map(cue => cue.text.trim()).filter(Boolean))].join('\n').slice(0,12000);
  // Danmaku is a community signal, not video content. Read only currently
  // visible text and keep it outside the primary subtitle/frame body so DOM
  // animation cannot make the visual observation look changed.
  const danmakuSelectors = [
    '.bpx-player-dm-dm', '.bpx-player-dm .bpx-player-dm-dm',
    '.bilibili-player-danmaku', '.danmaku-item', '.b-danmaku'
  ];
  const danmakuNodes = bilibili ? [...new Set(danmakuSelectors.flatMap(selector =>
    [...document.querySelectorAll(selector)]))] : [];
  const danmaku = [];
  for (const node of danmakuNodes) {
    if (!visible(node)) continue;
    const text = (node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 240);
    if (!text || danmaku.some(item => item.text === text)) continue;
    danmaku.push({text, media_time_seconds: video.currentTime});
    if (danmaku.length >= 24) break;
  }
  return {ok:true, url, media_identity, seeking:false, title:document.title.slice(0,512),
    observed_at:new Date().toISOString(), media_time_seconds:video.currentTime,
    paused:video.paused, ended:video.ended, playback_rate:video.playbackRate, ready_state:video.readyState,
    subtitles, image, frame_status, danmaku,
    cues, valid:!!subtitles || !!image,
    reason:cues.length ? null : 'current_subtitles_unavailable'};
}
