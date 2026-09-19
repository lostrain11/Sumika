// Mounted only inside a role preset. Reuse the native request waterfall without
// session/selectModel, which also changes defaults in DSH 0.1.5-rc.2.
export const name='sumika-role-model';

export function apply(ctx,config) {
  if (typeof config.enabled!=='boolean') throw Error('explicit role model enabled required');
  for (const key of ['provider','model']) {
    if (typeof config[key]!=='string'||!config[key].trim()) throw Error('explicit role model selection required');
  }
  if (config.reasoningEffort!==undefined && (typeof config.reasoningEffort!=='string'||!config.reasoningEffort.trim())) throw Error('invalid role reasoning effort');
  const selection=Object.freeze({provider:config.provider,model:config.model,
    ...(config.reasoningEffort===undefined?{}:{reasoningEffort:config.reasoningEffort})});
  ctx.on('agent/request',async(_event,next)=>{
    await next(); // Preserve native rejection; do not inherit the work model route.
    if (!config.enabled) throw Error('role model disabled');
    return {...selection};
  },{prepend:true});
}
