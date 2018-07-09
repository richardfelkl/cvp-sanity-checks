from jenkinsapi.jenkins import Jenkins
from xml.dom import minidom
from cvp_checks import utils
from pygerrit2 import GerritRestAPI, HTTPBasicAuth
import json
import pytest


def test_drivetrain_services_replicas(local_salt_client):
    salt_output = local_salt_client.cmd(
        'I@docker:host and not I@prometheus:server and not I@kubernetes:*',
        'cmd.run',
        ['docker service ls'],
        expr_form='compound')
    wrong_items = []
    for line in salt_output[salt_output.keys()[0]].split('\n'):
        if line[line.find('/') - 1] != line[line.find('/') + 1] \
           and 'replicated' in line:
            wrong_items.append(line)
    assert len(wrong_items) == 0, \
        '''Some DriveTrain services doesn't have expected number of replicas:
              {}'''.format(json.dumps(wrong_items, indent=4))


def test_drivetrain_components_and_versions(local_salt_client):
    config = utils.get_configuration()
    version = config['drivetrain_version'] or []
    if not version or version == '':
        pytest.skip("drivetrain_version is not defined. Skipping")
    salt_output = local_salt_client.cmd(
        'I@docker:host and not I@prometheus:server and not I@kubernetes:*',
        'cmd.run',
        ['docker service ls'],
        expr_form='compound')
    not_found_services = ['gerrit_db', 'gerrit_server', 'jenkins_master',
                          'jenkins_slave01', 'jenkins_slave02',
                          'jenkins_slave03', 'ldap_admin', 'ldap_server']
    version_mismatch = []
    for line in salt_output[salt_output.keys()[0]].split('\n'):
        for service in not_found_services:
            if service in line:
                not_found_services.remove(service)
                if version != line.split()[4].split(':')[1]:
                    version_mismatch.append("{0}: expected "
                        "version is {1}, actual - {2}".format(service,version,
                                                              line.split()[4].split(':')[1]))
                continue
    assert len(not_found_services) == 0, \
        '''Some DriveTrain components are not found:
              {}'''.format(json.dumps(not_found_services, indent=4))
    assert len(version_mismatch) == 0, \
        '''Version mismatch found:
              {}'''.format(json.dumps(version_mismatch, indent=4))


def test_jenkins_jobs_branch(local_salt_client):
    config = utils.get_configuration()
    expected_version = config['drivetrain_version'] or []
    if not expected_version or expected_version == '':
        pytest.skip("drivetrain_version is not defined. Skipping")
    jenkins_password = local_salt_client.cmd(
        'jenkins:client',
        'pillar.get',
        ['_param:openldap_admin_password'],
        expr_form='pillar').values()[0]
    jenkins_port = local_salt_client.cmd(
        'I@jenkins:client and not I@salt:master',
        'pillar.get',
        ['_param:haproxy_jenkins_bind_port'],
        expr_form='compound').values()[0]
    jenkins_address = local_salt_client.cmd(
        'I@jenkins:client and not I@salt:master',
        'pillar.get',
        ['_param:haproxy_jenkins_bind_host'],
        expr_form='compound').values()[0]
    version_mismatch = []
    jenkins_url = 'http://{0}:{1}'.format(jenkins_address,jenkins_port)
    server = Jenkins(jenkins_url, username='admin', password=jenkins_password)
    for job_name, job_instance in server.get_jobs():
        job_config = job_instance.get_config()
        xml_data = minidom.parseString(job_config)
        BranchSpec = xml_data.getElementsByTagName('hudson.plugins.git.BranchSpec')
        if BranchSpec:
            actual_version = BranchSpec[0].getElementsByTagName('name')[0].childNodes[0].data
            if actual_version != expected_version and 'master' not in actual_version:
                version_mismatch.append("Job {0} has {1} branch."
                                        "Expected {2}".format(job_instance.name,
                                                              actual_version,
                                                              expected_version))
    assert len(version_mismatch) == 0, \
        '''Some DriveTrain jobs have version/branch mismatch:
              {}'''.format(json.dumps(version_mismatch, indent=4))

def test_jenkins_plugins(local_salt_client):
    missing_plugins = []
    jenkins_password = local_salt_client.cmd(
        'jenkins:client',
        'pillar.get',
        ['_param:openldap_admin_password'],
        expr_form='pillar').values()[0]
    jenkins_port = local_salt_client.cmd(
        'I@jenkins:client and not I@salt:master',
        'pillar.get',
        ['_param:haproxy_jenkins_bind_port'],
        expr_form='compound').values()[0]
    jenkins_address = local_salt_client.cmd(
        'I@jenkins:client and not I@salt:master',
        'pillar.get',
        ['_param:haproxy_jenkins_bind_host'],
        expr_form='compound').values()[0]
    jenkins_url = 'http://{0}:{1}'.format(jenkins_address,jenkins_port)
    server = Jenkins(jenkins_url, username='admin', password=jenkins_password)
    installed_plugins = server.get_plugins()

    required_plugins = local_salt_client.cmd(
            'I@jenkins:client and not I@salt:master',
            'pillar.get',
            ['jenkins:client:plugin'],
            expr_form='compound').values()[0]

    for plugin in required_plugins:
        if plugin not in installed_plugins:
            missing_plugins.append("Jenkins has missing plugin {0}.".format(plugin))

    assert len(missing_plugins) == 0, \
        '''Some Jenkins plugins are not installed.:
              {}'''.format(json.dumps(missing_plugins, indent=4))

def test_gerrit_repositories(local_salt_client):
    missing_repos = []
    config = utils.get_configuration()
    gerrit_password = local_salt_client.cmd(
        'I@gerrit:client',
        'pillar.get',
        ['_param:openldap_admin_password'],
        expr_form='compound').values()[0]
    gerrit_port = local_salt_client.cmd(
        'I@gerrit:client',
        'pillar.get',
        ['gerrit:client:server:http_port'],
        expr_form='compound').values()[0]
    gerrit_address = local_salt_client.cmd(
        'I@gerrit:client',
        'pillar.get',
        ['gerrit:client:server:host'],
        expr_form='compound').values()[0]
    gerrit_protocol = local_salt_client.cmd(
        'I@gerrit:client',
        'pillar.get',
        ['gerrit:client:server:protocol'],
        expr_form='compound').values()[0]

    auth = HTTPBasicAuth('admin', gerrit_password)
    rest = GerritRestAPI(url="{0}://{1}:{2}".format(gerrit_protocol, gerrit_address, gerrit_port), auth=auth)

    for repo in config['drivetrain_repos']:
        repoHttp = repo.replace("/", "%2F")
        try:
            response = rest.get("/projects/{0}".format(repoHttp))
        except requests.exceptions.HTTPError as e:
            missing_repos.append("Repo {0} is missing".format(repo))


    assert len(missing_repos) == 0, \
        '''Some repositories in Gerrit are missing:
              {}'''.format(json.dumps(missing_repos, indent=4))
