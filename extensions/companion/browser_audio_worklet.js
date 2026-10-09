// No network or persistence. Chromium resamples the selected media stream into
// the owning 16kHz AudioContext before this bounded mono PCM16 conversion.
class SumikaPlayerPcm extends AudioWorkletProcessor {
  constructor(){super();this.samples=new Int16Array(1600);this.offset=0;}
  process(inputs,outputs){
    for(const output of outputs)for(const channel of output)channel.fill(0);
    const channels=inputs[0];
    if(!channels?.length)return true;
    for(let index=0;index<channels[0].length;index++){
      let value=0;
      for(const channel of channels)value+=channel[index]||0;
      value=Math.max(-1,Math.min(1,value/channels.length));
      this.samples[this.offset++]=Math.round(value<0?value*32768:value*32767);
      if(this.offset===1600){
        this.port.postMessage(this.samples.buffer,[this.samples.buffer]);
        this.samples=new Int16Array(1600);this.offset=0;
      }
    }
    return true;
  }
}
registerProcessor('sumika-player-pcm-v1',SumikaPlayerPcm);
