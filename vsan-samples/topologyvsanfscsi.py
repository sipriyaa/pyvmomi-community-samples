#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Copyright (c) 2019-2024 Broadcom. All Rights Reserved.
The term "Broadcom" refers to Broadcom Inc. and/or its subsidiaries.

This file includes sample codes for vCenter side vSAN file service API
accessing.

To provide an example of vSAN file service API acccess, it shows how to
download file service OVF, enable file service, create domain, create a
file share, remove a file share, remove domain, together with disable
file service.

"""

__author__ = 'Broadcom, Inc'
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, pbm, VmomiSupport, SoapStubAdapter
import sys
import ssl
import atexit
import argparse

#import the vSAN API python bindings
import vsanapiutils

# users can customize the parameters according to your own environment
DOMAIN_NAME = "cibgst.com"
IP_FQDN_DIC = {"166.168.31.10": "host10.cibgst.com",
               "166.168.31.11": "host11.cibgst.com",
               "166.168.31.12": "host12.cibgst.com",
               "166.168.31.13": "host13.cibgst.com"}
SUBNET_MASK = "255.255.0.0"
GATEWAY_ADDRESS = "166.168.31.253"
DNS_SUFFIXES = ["cibgst.com"]
DNS_ADDRESS = ["166.168.31.251"]

def GetArgs():
   """
   Supports the command-line arguments listed below.
   """
   parser = argparse.ArgumentParser(
       description='Process args for vSAN file service sample application')
   parser.add_argument('-s', '--host', required=True, action='store',
                       help='Remote host to connect to')
   parser.add_argument('-o', '--port', type=int, default=443, action='store',
                       help='Port to connect on')
   parser.add_argument('-u', '--user', required=True, action='store',
                       help='User name to use when connecting to host')
   parser.add_argument('-p', '--password', required=True, action='store',
                       help='Password to use when connecting to host')
   parser.add_argument('--cluster', dest='clusterName', metavar="CLUSTER",
                       default='VSAN-Cluster')
   args = parser.parse_args()
   return args

def getClusterInstance(clusterName, serviceInstance):
   content = serviceInstance.RetrieveContent()
   searchIndex = content.searchIndex
   datacenters = content.rootFolder.childEntity
   for datacenter in datacenters:
      cluster = searchIndex.FindChild(datacenter.hostFolder, clusterName)
      if cluster is not None:
         return cluster
   return None

def getFileServiceDomainConfig():
   networkProfiles = []
   for ipAddress, fqdn in IP_FQDN_DIC.items():
      networkProfile = vim.vsan.FileServiceIpConfig(
            dhcp=False, ipAddress=ipAddress, subnetMask=SUBNET_MASK,
            gateway=GATEWAY_ADDRESS, fqdn=fqdn)
      networkProfiles.append(networkProfile)
   networkProfiles[0].isPrimary = True

   fileServiceDomainConfig = vim.vsan.FileServiceDomainConfig(
         name = DOMAIN_NAME,
         dnsServerAddresses = DNS_ADDRESS,
         dnsSuffixes = DNS_SUFFIXES,
         fileServerIpConfig = networkProfiles)

   return fileServiceDomainConfig

def connectToSpbm(stub, context):
   hostname = stub.host.split(":")[0]
   sessionCookie = stub.cookie.split('"')[1]
   VmomiSupport.GetRequestContext()["vcSessionCookie"] = sessionCookie

   pbmStub = SoapStubAdapter(
         host=hostname,
         path = "/pbm/sdk",
         version = "pbm.version.version2",
         sslContext=context,
         )
   pbmStub.cookie = stub.cookie
   pbmSi = pbm.ServiceInstance("ServiceInstance", pbmStub)
   return pbmSi

def getVsanStoragePolicy(pbmSi):
   resourceType = pbm.profile.ResourceType(
      resourceType=pbm.profile.ResourceTypeEnum.STORAGE
   )

   profileManager = pbmSi.RetrieveContent().profileManager
   profileIds = profileManager.PbmQueryProfile(resourceType)
   profiles = profileManager.PbmRetrieveContent(profileIds)
   for profile in profiles:
      # vSAN default storage profile possesses a unique profile ID of
      # 'aa6d5a82-1c88-45da-85d3-3d74b91a5bad' across different releases.
      profileId = profile.profileId.uniqueId
      if (isinstance(profile, pbm.profile.CapabilityBasedProfile) and
            profileId == 'aa6d5a82-1c88-45da-85d3-3d74b91a5bad'):
         return vim.VirtualMachineDefinedProfileSpec(profileId=profileId)
   return None

def getFileShareConfig(stub, context, domainName):
   shareName, shareQuota = 'TestShare-1', '10G'
   pbmSi = connectToSpbm(stub, context)
   vsanStoragePolicy = getVsanStoragePolicy(pbmSi)
   if vsanStoragePolicy is None:
      print("Cannot find the vSAN Storage Policy from VC server")
      return None

   netPermissions = vim.vsan.FileShareNetPermission(
         ips='*',
         permissions=vim.vsan.FileShareAccessType.READ_WRITE,
         allowRoot=True)
   sharePermissions = [netPermissions]
   fileShareConfig = vim.vsan.FileShareConfig(
         name=shareName,
         domainName=domainName,
         quota=shareQuota,
         storagePolicy=vsanStoragePolicy,
         permission=sharePermissions)
   return fileShareConfig

def main():
   args = GetArgs()
   if args.password:
      password = args.password
   else:
      password = getpass.getpass(prompt='Enter password for VC %s and '
                                 'user %s: ' % (args.host, args.user))
   # For python 2.7.9 and later, the default SSL context has more strict
   # connection handshaking rule. We may need turn off the hostname checking
   # and client side cert verification.
   context = None
   if sys.version_info[:3] > (2,7,8):
      context = ssl.create_default_context()
      context.check_hostname = False
      context.verify_mode = ssl.CERT_NONE

   # Connect to vCenter, get vc service instance
   si = SmartConnect(host=args.host,
                     user=args.user,
                     pwd=password,
                     port=int(args.port),
                     sslContext=context)
   atexit.register(Disconnect, si)

   # Detecting whether the host is vCenter or ESXi.
   aboutInfo = si.content.about
   apiVersion = vsanapiutils.GetLatestVmodlVersion(args.host, int(args.port))

   if aboutInfo.apiType != 'VirtualCenter':
      print("The vSAN file service APIs are only available on vCenter")
      return -1

   cluster = getClusterInstance(args.clusterName, si)
   if cluster is None:
      print("Cluster %s is not found for %s" % (args.clusterName, args.host))
      return -1

   vcMos = vsanapiutils.GetVsanVcMos(si._stub, context=context,
                                     version=apiVersion)
   vcfs = vcMos['vsan-cluster-file-service-system']
   vccs = vcMos['vsan-cluster-config-system']

   # Find OVF download url
   print("Finding OVF download url ...")
   ovfUrl = vcfs.FindOvfDownloadUrl(cluster)
   if not ovfUrl:
      print("Failed to find the OVF download url.")
      return -1
   print("Found OVF download url: %s" % ovfUrl)

   # Download FSVM OVF files to vCenter
   print("Downloading ovf files from %s to vCenter ..." % ovfUrl)
   vsanTask = vcfs.DownloadFileServiceOvf(downloadUrl=ovfUrl)
   vcTask = vsanapiutils.ConvertVsanTaskToVcTask(vsanTask, si._stub)
   vsanapiutils.WaitForTasks([vcTask], si)
   if vcTask.info.state != 'success':
      print("Failed to download ovf files with error: %s"
            % vcTask.infor.error)
      return -1
   print("Downloaded ovf files to vCenter successfully")

   # Enable file service
   print("Enabling the file service")
   net = None
   network = None

   for network_local in cluster.host[0].network:
     if isinstance(network_local, vim.Network) and network_local.name == "workload-network":
        net = network_local
        break

   if net:
      network = net
   else:
     network = cluster.host[0].network[0]
   
   fileServiceConfig = vim.vsan.FileServiceConfig(
         enabled=True,
         network=network,
         domains=[],
   )
   clusterSpec = vim.vsan.ReconfigSpec(fileServiceConfig=fileServiceConfig)
   vsanTask = vccs.ReconfigureEx(cluster, clusterSpec)
   vcTask = vsanapiutils.ConvertVsanTaskToVcTask(vsanTask, si._stub)
   vsanapiutils.WaitForTasks([vcTask], si)
   if vcTask.info.state != 'success':
      print("Failed to enable file service with error: %s"
            % vcTask.info.error)
      return -1
   print("Enabled file service successfully")

   # Create file service domain
   fsDomainConfig = getFileServiceDomainConfig()
   domainName = fsDomainConfig.name
   print("Creating file service domain")
   vsanTask = vcfs.CreateFileServiceDomain(fsDomainConfig, cluster)
   vcTask = vsanapiutils.ConvertVsanTaskToVcTask(vsanTask, si._stub)
   vsanapiutils.WaitForTasks([vcTask], si)
   if vcTask.info.state != 'success':
      print("Failed to create file service domain with error: %s"
            % vcTask.info.error)
      return -1
   print("Created file service domain %s successfully"
         % domainName)

if __name__ == "__main__":
   main()
