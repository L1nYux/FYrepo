function currentMessage(installed,formal){
  if(!formal)return '当前安装版本 '+installed+'，暂时没有可用的正式更新。';
  if(installed!==formal)return '当前安装版本 '+installed+'；正式更新渠道版本 '+formal+'，没有可用的更高版本更新。';
  return '当前安装版本 '+installed+'，已是正式更新渠道的最新版本。';
}
module.exports={currentMessage};
