const test=require('node:test'),assert=require('node:assert/strict');
const {publicAddress,address}=require('../public-browser.cjs');
test('public browser blocks private and reserved IP networks',()=>{for(const value of ['127.0.0.1','10.0.0.1','172.16.0.1','192.168.1.1','169.254.169.254','100.64.0.1','0.0.0.0','224.0.0.1','::1','::ffff:127.0.0.1','fd00::1'])assert.equal(publicAddress(value),false,value);assert.equal(publicAddress('8.8.8.8'),true);});
test('browser URLs cannot include credentials or non-web schemes',()=>{for(const value of ['file:///C:/Users/','javascript:alert(1)','https://u:p@example.com/','http://example.com:9000/'])assert.throws(()=>address(value));assert.equal(address('https://example.com/').hostname,'example.com');});
