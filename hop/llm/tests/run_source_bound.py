"""Focused native v7/request checks; same disposable setup as the full LLM suite."""
import os
import subprocess
import time
import run as fixture
from v7_checks import check_v7_native


def main():
    f=fixture
    for name in [f.PG,f.HOP,f.MOCK]:
        assert subprocess.run(['docker','inspect',name],capture_output=True).returncode,'Existing fixture; inspect before resetting'
    created=[]
    network_created=False
    try:
        if subprocess.run(['docker','network','inspect',f.PREFIX],capture_output=True).returncode:
            f.cmd(['docker','network','create','--internal',f.PREFIX])
            network_created=True
        for name,image,args in [
            (f.PG,'postgres:17-alpine',['-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=hoptest']),
            (f.HOP,'apache/hop:2.19.0',['--entrypoint','/bin/sleep'])]:
            f.cmd(['docker','run','-d','--name',name,'--network',f.PREFIX]+args+[image]+(['infinity'] if name==f.HOP else []))
            created.append(name)
        for _ in range(30):
            if subprocess.run(['docker','exec',f.PG,'pg_isready','-U','postgres','-d','hoptest'],capture_output=True).returncode==0:break
            time.sleep(.2)
        f.seed();created.append(f.MOCK);endpoint=f.stage()
        f.run_hop('install.hwf',{},'source-bound-native-installer')
        f.run_hop('prepare_evaluation.hwf',dict(DATASET_ID='test-ko',DATASET_SIZE=2),'source-bound-prepare-dataset')
        params=dict(DATASET_ID='test-ko',POSTING_LIMIT=2,PROMPT_VERSION='ko-v7',EXECUTE_REQUESTS='Y',
            ENDPOINT=endpoint,API_KEY_FILE=f.REMOTE+'/key.csv',EXTRACT_MODEL='test/extractor',
            CATEGORIZE_MODEL='test/categorizer',PROVIDER_ONLY='deepinfra',REQUEST_DELAY_MS=1,READ_TIMEOUT_MS=5000)
        check_v7_native(f.sql,f.js,f.q,f.run_hop,params,f.request_count)
        print('SOURCE-BOUND FOCUSED CHECKS PASSED. Logs:',f.WORK,flush=True)
    finally:
        if not os.environ.get('KEEP_LLM_TEST_CONTAINERS'):
            if created:subprocess.run(['docker','rm','-fv']+created,capture_output=True)
            if network_created:subprocess.run(['docker','network','rm',f.PREFIX],capture_output=True)


if __name__=='__main__':main()
