// UI tests must fail and exit when their launcher/log pipe disappears.
// This module is used only by test entry points, never by the packaged app.
function installRuntime(app,{stdout=process.stdout,stderr=process.stderr,timeoutMs=180000}={}){
  let stopping=false;
  const stop=()=>{if(stopping)return;stopping=true;app.exit(1);};
  stdout.on('error',stop);stderr.on('error',stop);
  const deadline=setTimeout(stop,timeoutMs);deadline.unref();
  return ()=>{clearTimeout(deadline);stdout.removeListener('error',stop);stderr.removeListener('error',stop);};
}
module.exports={installRuntime};
