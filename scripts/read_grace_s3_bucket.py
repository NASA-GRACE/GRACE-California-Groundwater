import requests
#import s3fs
import numpy as np
import xarray as xr

#Written by Munish Sikka
def store_aws_keys(endpoint: str="https://archive.podaac.earthdata.nasa.gov/s3credentials"):    
    with requests.get(endpoint, "w") as r:
        accessKeyId, secretAccessKey, sessionToken, expiration = list(r.json().values())

    creds ={}
    creds['AccessKeyId'] = accessKeyId
    creds['SecretAccessKey'] = secretAccessKey
    creds['SessionToken'] = sessionToken
    creds['expiration'] = expiration
    
    return creds


def grace_connection(ShortName,grace_filename):
    #Source: Jinbo Wang (Email: jinbo.wang@jpl.nasa.gov)
    creds = store_aws_keys()
    #print(creds)
    s3 = s3fs.S3FileSystem(
    key = creds['AccessKeyId'],
    secret = creds['SecretAccessKey'],
    token = creds['SessionToken'],
    client_kwargs = {'region_name':'us-west-2'},
    )
    #print(f"\nThe current session token expires at {creds['expiration']}.\n")

# Ask PODAAC for the collection id using the 'short name'
    response = requests.get(
        url='https://cmr.earthdata.nasa.gov/search/collections.umm_json', 
        params={'provider': "POCLOUD",
                'ShortName': ShortName,
                'page_size': 1}
    )

    ummc = response.json()['items'][0]
    ccid = ummc['meta']['concept-id']
    #print(f'collection id: {ccid}')

    ss="podaac-ops-cumulus-protected/%s/*.nc"%ShortName
    GRACE_s3_files = np.sort(s3.glob(ss))
    full_filename=f'podaac-ops-cumulus-protected/TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.1_V3/{grace_filename}'
    dataset = xr.open_dataset(s3.open(full_filename))
        
    return dataset

def read_grace_dataset(ShortName,grace_filename):
    dataset = grace_connection(ShortName,grace_filename)
    
    return dataset

