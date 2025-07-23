from lxml import etree
'''
parse gerrit android manifest file to multi repo
'''
class MParser():
    def __init__(self, **kwargs):
        self.projectId = kwargs.get('projectId', None)
    
    
    def run(self, content):
        root = etree.fromstring(content)
        root = list(root.iter('manifest'))[0]
        remotes = {}
        projects = []
        '''
        AOSP约定结构
        '''
        # TODO 深层次追踪
        _includes = list(root.iter("include"))# 可选
        _projects = list(root.iter("project"))# 至少一个
        _default = list(root.iter("default"))# 可选，至多一个
        _remotes = list(root.iter("remote"))# 至少一个
        # 1. 取remote
        for _rObj in _remotes:
            remotes[_rObj.get("name")] = _rObj.get("fetch")
        default = {"name": _default[0].get("remote"), 'revision': _default[0].get("revision")}
        # 当project中未标记remote时，则使用default对应的remote
        for _pObj in _projects:
            temp = {"field": "1", "trinityProjectId": self.projectId}
            _ = _pObj.get('revision', None)
            temp["branch"] = _ if _ != None else default['revision']
            _r = _pObj.get('remote', None)
            if _r == None:
                _r = remotes[default['name']]
            else:
                _r = remotes[_r]
            _n = _pObj.get("name", '')
            temp["target"] = f"{_r}/{_n} -b {_}"
            projects.append(temp)
        return projects
