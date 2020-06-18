import os
import sys
import getopt

from dabstract.dataset.helpers import dataset_from_config
from dabstract.utils import load_yaml_config
from dabstract.dataprocessor import processing_chain
os.environ["dabstract_CUSTOM_DIR"] = "dabstract_custom"

def flow_feature_extraction(cg_in=dict(),co_in=dict()):
    # -- General params
    cg = {'dataset': 'EXAMPLE',
          'key': 'data',
          'features': 'EXAMPLE'}
    # general
    co = {'dir_conf': 'local_server',
          'overwrite': False,
          'verbose': True,
          'multi_processing': False,
          'workers': 5,
          'buffer_len': 5}
    # --- parameter overloading
    cg.update(cg_in), co.update(co_in)
    # -- get dirs
    dirs = load_yaml_config(filename=co['dir_conf'], dir=os.path.join('configs', 'dirs'), walk=True)
    # -- get_dataset
    data = load_yaml_config(filename=cg['dataset'], dir=os.path.join('configs', 'db'), walk=True,
                            post_process=dataset_from_config, **dirs)
    # -- get processing chain
    fe_dp = load_yaml_config(filename=cg['features'], dir=os.path.join('configs', 'dp'), walk=True,
                             post_process=processing_chain)
    # -- get features
    data.prepare_feat(cg['key'],
                      cg['features'],
                      fe_dp,
                      overwrite=co['overwrite'],
                      verbose=co['verbose'],
                      new_key='feat',
                      multi_processing=co['multi_processing'],
                      workers=co['workers'],
                      buffer_len=co['buffer_len'])

if __name__ == "__main__":
    try:
        sys.exit(flow_feature_extraction())

    except (ValueError, IOError) as e:
        sys.exit(e)


