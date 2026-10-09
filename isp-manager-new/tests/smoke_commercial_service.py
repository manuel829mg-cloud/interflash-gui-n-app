import os
import tempfile
from unittest.mock import patch
from html.parser import HTMLParser

with tempfile.TemporaryDirectory() as directory:
    os.environ['DB_PATH']=directory+'/smoke.db'
    os.environ['SECRET_KEY']='isolated-smoke'
    with patch('threading.Thread.start'):
        import wsgi
    import app as base
    c=base.db()
    plan=c.execute('SELECT id FROM plans WHERE download_mbps=20 AND active=1').fetchone()[0]
    c.execute("INSERT INTO customers(id,name,pppoe,plan_id,mikrotik_profile,router_name,pbr_line,ip_address) VALUES(1,'Prueba','prueba',?,'20M-HSGQ','CCR2116','Linea-4-Altice','10.55.55.59')",(plan,))
    c.execute("INSERT INTO push_ppp_profiles(router_name,name,rate_limit,remote_address,local_address) VALUES('CCR2116','20M-HSGQ','20M/20M','Pool-HSGQ','10.55.55.1')")
    c.commit();c.close()
    client=base.app.test_client()
    with client.session_transaction() as session:session['auth']=True
    for path in ('/customers/new','/customers/1/edit','/customers/1/profile'):
        response=client.get(path)
        assert response.status_code==200,(path,response.status_code)
        html=response.get_data(as_text=True)
        assert 'type="hidden" name="mikrotik_profile"' in html,path
        assert 'window.IFPROFILE=' not in html,path
        assert '<select id="if-profile-select"' not in html,path
        assert 'commercial-profile' in html,path
        print(path,'OK')
    response=client.get('/api/mikrotik/commercial-profile?customer_id=1&plan_id='+str(plan))
    assert response.json=={'ok':True,'profile':'20M-HSGQ'},response.json
    c=base.db();assert c.execute('SELECT COUNT(*) FROM router_commands').fetchone()[0]==0;c.close()
    print('profile API and no router commands: OK')
