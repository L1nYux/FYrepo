const test=require('node:test'),assert=require('node:assert/strict');
const {publicAddress,address,safeUserAgent}=require('../public-browser.cjs');
test('localized app names produce ASCII-only browser request headers',()=>{
  const value=safeUserAgent('Mozilla/5.0 知域/0.2.20 Chrome/152');
  assert.equal(value,'Mozilla/5.0 Zhiyu/0.2.20 Chrome/152');
  assert.equal(new Headers({'User-Agent':value}).get('User-Agent'),value);
  assert.equal(safeUserAgent(value),value);
});
test('public browser blocks private and reserved IP networks',()=>{for(const value of ['127.0.0.1','10.0.0.1','172.16.0.1','192.168.1.1','169.254.169.254','100.64.0.1','0.0.0.0','224.0.0.1','::1','::ffff:127.0.0.1','fd00::1'])assert.equal(publicAddress(value),false,value);assert.equal(publicAddress('8.8.8.8'),true);});
test('browser URLs cannot include credentials or non-web schemes',()=>{for(const value of ['file:///C:/Users/','javascript:alert(1)','https://u:p@example.com/','http://example.com:9000/'])assert.throws(()=>address(value));assert.equal(address('https://example.com/').hostname,'example.com');});
