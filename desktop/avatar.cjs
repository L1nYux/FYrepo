const MAX_BYTES=512*1024;
async function fetchAvatar(session,origin,url){
  if(!/^\/accounts\/\d+\/avatar\/[a-f0-9]{32}\/$/.test(url||''))return '';
  const response=await session.fetch(origin+url,{credentials:'include',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(4000)});
  if(!response.ok||response.headers.get('content-type')!=='image/webp')return '';
  const reader=response.body.getReader(),chunks=[];let size=0;
  try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>MAX_BYTES)return '';chunks.push(Buffer.from(value));}}
  finally{await reader.cancel().catch(()=>{});}
  const buffer=Buffer.concat(chunks);
  if(buffer.length<12||buffer.toString('ascii',0,4)!=='RIFF'||buffer.toString('ascii',8,12)!=='WEBP')return '';
  return 'data:image/webp;base64,'+buffer.toString('base64');
}
module.exports={fetchAvatar};
