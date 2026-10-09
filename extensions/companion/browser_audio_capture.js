// Fixed media-element adapter. The host supplies the bundled worklet and the
// existing passive snapshot reader; page text never supplies code or consent.
(config) => {
  if (config.consent !== true) throw new Error('explicit player audio consent required');
  if (!['https://www.bilibili.com','https://bilibili.com'].includes(config.origin) ||
      location.origin !== config.origin || typeof config.readSnapshot !== 'function' ||
      typeof config.onPcm !== 'function') throw new Error('fixed player audio scope required');
  let current=null, epoch=0, state='stopped', reason=null;
  const status=()=>({state,reason,packets:current?.packets||0});
  const identity=snapshot=>JSON.stringify(snapshot.media_identity);
  const release=async owner=>{
    if(!owner)return;
    clearInterval(owner.timer);
    for(const [name,listener] of owner.listeners||[])owner.video.removeEventListener(name,listener);
    if(owner.node)owner.node.port.onmessage=null;
    for(const node of [owner.source,owner.node,owner.sink])try{node?.disconnect();}catch{}
    owner.stream?.getTracks().forEach(track=>track.stop());
    if(owner.context && owner.context.state!=='closed')await owner.context.close();
  };
  const stop=async(why=null)=>{
    const owner=current;current=null;epoch++;
    state=why?'unavailable':'stopped';reason=why;
    await release(owner);
    return status();
  };
  const snapshot=()=>config.readSnapshot({origin:config.origin,capture_frame:false});
  const matches=owner=>{
    const value=snapshot();
    return owner.video.isConnected && value.ok && !value.paused && !value.seeking && !value.ended &&
      value.playback_rate===owner.rate && identity(value)===owner.identity;
  };
  const start=async()=>{
    if(current)throw new Error('player audio already active');
    if(location.origin!==config.origin)throw new Error('player origin changed');
    const initial=snapshot();
    if(!initial.ok || initial.paused || initial.seeking || initial.ended)
      throw new Error('unambiguous playing video required');
    const videos=[...document.querySelectorAll('video')].filter(video=>{
      const r=video.getBoundingClientRect(),s=getComputedStyle(video);
      return r.width>0 && r.height>0 && r.bottom>0 && r.right>0 && r.top<innerHeight && r.left<innerWidth &&
        s.visibility!=='hidden' && s.display!=='none';
    });
    if(videos.length!==1 || typeof videos[0].captureStream!=='function')
      throw new Error('media element audio capture unavailable');
    const owner=current={epoch:++epoch,video:videos[0],identity:identity(initial),
      media_identity:initial.media_identity,rate:initial.playback_rate,packets:0,busy:false,listeners:[]};
    state='starting';reason=null;
    try {
      owner.stream=owner.video.captureStream();
      if(!owner.stream.getAudioTracks().length)throw new Error('player audio track unavailable');
      owner.stream.getVideoTracks().forEach(track=>track.stop());
      owner.context=new AudioContext({sampleRate:16000});
      if(owner.context.sampleRate!==16000)throw new Error('16kHz browser audio unavailable');
      await owner.context.audioWorklet.addModule(config.workletUrl);
      if(current!==owner || owner.epoch!==epoch)throw new Error('player audio start revoked');
      if(!matches(owner))throw new Error('player changed during audio start');
      owner.node=new AudioWorkletNode(owner.context,'sumika-player-pcm-v1',{
        numberOfInputs:1,numberOfOutputs:1,outputChannelCount:[1]});
      owner.source=owner.context.createMediaStreamSource(new MediaStream(owner.stream.getAudioTracks()));
      owner.sink=owner.context.createGain();owner.sink.gain.value=0;
      owner.source.connect(owner.node);owner.node.connect(owner.sink);owner.sink.connect(owner.context.destination);
      owner.node.port.onmessage=event=>{
        if(current!==owner || owner.epoch!==epoch)return;
        if(!matches(owner)){void stop('player_changed');return;}
        const data=event.data;
        if(!(data instanceof ArrayBuffer) || data.byteLength!==3200){void stop('invalid_audio_packet');return;}
        // At most one 100ms packet is handed to an asynchronous consumer. A
        // slow consumer fails closed instead of accumulating unbounded PCM.
        if(owner.busy){void stop('audio_consumer_overflow');return;}
        owner.busy=true;
        const sequence=owner.packets++;
        Promise.resolve().then(()=>{
          if(current!==owner || owner.epoch!==epoch)return;
          return config.onPcm({pcm:new Uint8Array(data),sample_rate:16000,sequence,
            sample_offset:sequence*1600,media_identity:owner.media_identity,
            track:'selected-media-element',media_position_known:false});
        }).catch(()=>{if(current===owner)void stop('audio_consumer_failed');})
          .finally(()=>{owner.busy=false;});
      };
      const revoke=()=>{if(current===owner)void stop('player_changed');};
      for(const track of owner.stream.getAudioTracks())track.addEventListener('ended',revoke,{once:true});
      for(const name of ['seeking','emptied','pause','ended','ratechange']){
        owner.video.addEventListener(name,revoke);owner.listeners.push([name,revoke]);
      }
      owner.timer=setInterval(()=>{if(current===owner && !matches(owner))revoke();},100);
      await owner.context.resume();
      if(current!==owner || owner.epoch!==epoch)throw new Error('player audio start revoked');
      state='recording';return status();
    } catch(error) {
      if(current===owner)await stop(error.message);
      else await release(owner);
      throw error;
    }
  };
  return {start,stop,status};
}
