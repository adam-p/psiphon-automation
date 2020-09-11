#!/usr/bin/python
#
# Copyright (c) 2020, Psiphon Inc.
# All rights reserved.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import os
import sys
import random
import string
import time
import psi_ssh
import psi_utils

# Import Linode APIv4 Official Library
# COMMENT: need pip install openstack to install dependency
import openstack

# VARIABLE
tcs_image_id = {
    'NYC': '4d207ea9-8e1e-4cff-af94-29f93f7a90ad',
    'SEA': '',
    'NL': '',
    'LA': '',
    'ATL': ''
}

#2GB SKVM - 9c6425e1-d36e-4b9a-bdb2-4e64f811280a
#4GB SKVM - 33920162-e6bd-4d48-9daa-2509beb913cb
size_flavor = '9c6425e1-d36e-4b9a-bdb2-4e64f811280a'
#==============================================================================

###
#
# Helper functions
# TODO: This can be changed to OpenStack build in function client.compute.wait_for_server()
# https://docs.openstack.org/openstacksdk/latest/user/proxies/compute.html
#
###
def wait_while_condition(condition, max_wait_seconds, description):
    total_wait_seconds = 0
    wait_seconds = 5
    while condition() == True:
        if total_wait_seconds > max_wait_seconds:
            raise Exception('Took more than %d seconds to %s' % (max_wait_seconds, description))
        time.sleep(wait_seconds)
        total_wait_seconds = total_wait_seconds + wait_seconds

###
#
# General API Interaction functions
#
###
class PsiRamnode:
    def __init__(self, ramnode_account):
        self.region = random.choice(ramnode_account.available_regions)
        ramnode_api_credentials = {}
        ramnode_api_credentials['project_id'] = ramnode_account.project_id
        ramnode_api_credentials['username'] = ramnode_account.api_username
        ramnode_api_credentials['password'] = ramnode_account.api_password
        ramnode_api_credentials['user_domain_name'] = ramnode_account.api_default
        ramnode_api_credentials['project_domain_name'] = ramnode_account.api_default
        ramnode_api_credentials['region_name'] = self.region
        ramnode_api_credentials['auth_url'] = 'https://nyc-controller.ramnode.com:5000/v3'
        self.client = openstack.connect(**ramnode_api_credentials)

    def get_available_regions(self):
        # Get all available regions
        return self.client.identity.regions()

    def get_region(self, region):
        # Get region's country code
        if region in ['SEA','NYC','LA','ATL']:
            country_code = 'US'
        elif region in ['NL']:
            country_code = 'NL'
        return country_code

    def get_datacenter_names(self, region):
        # from linode_api.get_available_regions():
        regions = {
            'NYC': 'Ramnode Cloud New York, US',
            'SEA': 'Ramnode Cloud Seattle, US',
            'LA': 'Ramnode Cloud Los Angeles, US',
            'ATL': 'Ramnode Cloud Atlanta, US',
            'NL': 'Ramnode Cloud Amsterdam, Netherland'
        }
        return regions.get(region, "")

    def list_ramnodes(self):
        # return all linodes in the account.
        return self.client.compute.servers()

    def ramnode_list(self, ramnode_id):
        # List single linode by searching its id
        return self.client.compute.get_server(ramnode_id)

    def ramnode_status(self, ramnode_id):
        # Return Ramnode status
        # Status:
        # ACTIVE, 
        # BUILDING, 
        # DELETED, 
        # ERROR, 
        # HARD_REBOOT, 
        # PASSWORD, 
        # PAUSED, 
        # REBOOT, 
        # REBUILD, 
        # RESCUED, 
        # RESIZED, 
        # REVERT_RESIZE, 
        # SHUTOFF, 
        # SOFT_DELETED, 
        # STOPPED, 
        # SUSPENDED, 
        # UNKNOWN, 
        # VERIFY_RESIZE.
        return self.ramnode_list(ramnode_id).status

    def remove_ramnode(self, ramnode_id):
        return self.client.compute.delete_server(ramnode_id)
    
    def create_ramnode(self, host_id):
        choice_region = self.region
        datacenter_name = self.get_datacenter_names(choice_region)

        # We are using 2G: u'2GB SKVM'
        # TODO: Need to finish the server object
        ramnode = self.client.compute.create_server(name=host_id, flavorRef=size_flavor, networks=[], imageRef=tcs_image_id)
        
        # Wait for job completion
        self.client.compute.wait_for_server(ramnode, status='ACTIVE', interval=5, wait=60)

        return ramnode, datacenter_name, self.get_region(choice_region)

    def start_ramnode(self, ramnode_id, config=None):
        # Boot linode from API
        ramnode = self.ramnode_list(ramnode_id)
        self.client.compute.start_server(ramnode)

        # Wait for job completion
        self.client.compute.wait_for_server(ramnode, status='ACTIVE', interval=5, wait=60)

    def stop_linode(self, linode_id):        
        # Shutdown linode from API
        ramnode = self.ramnode_list(ramnode_id)
        self.client.compute.stop_server(ramnode)

        # Wait for job completion
        self.client.compute.wait_for_server(ramnode, status='SHUTOFF', interval=5, wait=60)
    
    def restart_linode(self, linode_id):
        # Restart from API
        ramnode = self.ramnode_list(ramnode_id)
        self.client.compute.reboot_server(ramnode, reboot_type='HARD')

        # Wait for job completion
        self.client.compute.wait_for_server(ramnode, status='ACTIVE', interval=5, wait=60)

###
#
# Server side SSH Interaction functions (Migrated from old code)
#
###
def refresh_credentials(ramnode_account, ip_address, password, host_public_key, new_root_password, new_stats_password, stats_username):
    ssh = psi_ssh.make_ssh_session(ip_address, ramnode_account.base_ssh_port,
                                   'root', password, host_public_key)
    ssh.exec_command('echo "root:%s" | chpasswd' % (new_root_password,))
    ssh.exec_command('useradd -M -d /var/log -s /bin/sh -g adm %s' % (stats_username))
    ssh.exec_command('echo "%s:%s" | chpasswd' % (stats_username, new_stats_password))
    ssh.exec_command('rm /etc/ssh/ssh_host_*')
    ssh.exec_command('rm -rf /root/.ssh')
    ssh.exec_command('dpkg-reconfigure openssh-server')
    return ssh.exec_command('cat /etc/ssh/ssh_host_rsa_key.pub')

def set_allowed_users(ramnode_account, ip_address, password, host_public_key, stats_username):
    ssh = psi_ssh.make_ssh_session(ip_address, ramnode_account.base_ssh_port,
                                   'root', password, host_public_key)
    user_exists = ssh.exec_command('grep %s /etc/ssh/sshd_config' % stats_username)
    if not user_exists:
        ssh.exec_command('sed -i "s/^AllowUsers.*/& %s/" /etc/ssh/sshd_config' % stats_username)
        ssh.exec_command('service ssh restart')

def set_host_name(ramnode_account, ip_address, password, host_public_key, new_hostname):
    # Note: hostnamectl is for systemd servers
    ssh = psi_ssh.make_ssh_session(ip_address, ramnode_account.base_ssh_port,
                                   'root', password, host_public_key)
    ssh.exec_command('hostnamectl set-hostname %s' % new_hostname)

###
#
# Main function
#
###
def get_servers(ramnode_account):
    ramnode_api = PsiRamnode(ramnode_account)
    ramnodes = ramnode_api.list_ramnodes()
    return [(str(rn.id), rn.hostname) for rn in ramnodes]

def get_server(ramnode_account, ramnode_id):
    ramnode_api = PsiRamnode(ramnode_account)
    ramnode =ramnode_api.ramnode_list(ramnode_id)
    return ramnode

def remove_server(ramnode_account, ramnode_id):
    ramnode_api = PsiRamnode(ramnode_account)
    try:
        ramnode_api.remove_ramnode(int(ramnode_id))
    except Exception as ex:
        raise ex

def launch_new_server(ramnode_account, is_TCS, plugins, multi_ip=False):

    ramnode = None
    ramnode_id = None
    ramnode_api = PsiRamnode(ramnode_account) # Use new API interface

    if is_TCS:
        # New APIv4 require root_pass when create disk from image
        root_password = ramnode_account.tcs_base_root_password
        host_public_key = ramnode_account.tcs_base_host_public_key #TODO: Double check if host_public key stay same

    try:
        hostname = 'rn-' + ramnode_api.region.lower() + ''.join(random.choice(string.ascii_lowercase) for x in range(8))

        # Create a new linode
        new_root_password = psi_utils.generate_password()
        ramnode, datacenter_name, region = ramnode_api.create_ramnode(hostname)
        
        ramnode_ip_address = ramnode.addresses['Public'][0]['addr']
        egress_ip_address = None

        if is_TCS:
            # Ramnodes created by an image keep the image's hostname.  Override this
            set_host_name(ramnode_account, ramnode_ip_address, root_password,
                          host_public_key, hostname)
            stats_username = psi_utils.generate_stats_username()
            set_allowed_users(ramnode_account, ramnode_ip_address, root_password,
                              host_public_key, stats_username)
        
        # Change the new linode's credentials
        new_stats_password = psi_utils.generate_password()
        new_host_public_key = refresh_credentials(ramnode_account, ramnode_ip_address,
                                                  root_password, host_public_key,
                                                  new_root_password, new_stats_password,
                                                  stats_username)

    except Exception as ex:
        if ramnode:
            ramnode_api.remove_ramnode(ramnode.id)
        raise ex
    finally:
        # New: we'll leave this on now due to parallelization
        pass

    return (hostname, is_TCS, 'NATIVE' if is_TCS else None, None, str(ramnode.id), ramnode_ip_address,
            ramnode_account.base_ssh_port, 'root', new_root_password,
            ' '.join(new_host_public_key.split(' ')[:2]),
            stats_username, new_stats_password,
            datacenter_name, region, None, None, None, None, None, None, None, None)

if __name__ == "__main__":
    print launch_new_server()
