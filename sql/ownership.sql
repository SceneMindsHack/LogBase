-- FICTIONAL ownership for demonstrations, not ownership inferred from logs.
CREATE TABLE IF NOT EXISTS component_ownership (
    dataset TEXT, component TEXT, team TEXT
);
INSERT INTO component_ownership
SELECT dataset, component, team FROM (VALUES
 ('bgl', 'KERNEL', 'Compute Reliability'),
 ('bgl', 'LINKCARD', 'Infrastructure'),
 ('bgl', 'APP', 'Application Operations'),
 ('bgl', 'MMCS', 'Platform Operations'),
 ('bgl', 'HARDWARE', 'Infrastructure'),
 ('bgl', 'DISCOVERY', 'Platform Operations'),
 ('bgl', 'CMCS', 'Platform Operations'),
 ('bgl', 'BGLMASTER', 'Platform Operations'),
 ('bgl', 'MONITOR', 'Platform Operations'),
 ('bgl', 'SERV_NET', 'Infrastructure'),
 ('openstack', 'nova.osapi_compute.wsgi.server', 'Cloud API'),
 ('openstack', 'nova.compute.manager', 'Cloud Compute'),
 ('openstack', 'nova.virt.libvirt.imagecache', 'Cloud Compute'),
 ('openstack', 'nova.api.openstack.compute.server_external_events', 'Cloud API'),
 ('openstack', 'nova.virt.libvirt.driver', 'Cloud Compute'),
 ('openstack', 'nova.compute.resource_tracker', 'Cloud Compute'),
 ('openstack', 'nova.metadata.wsgi.server', 'Cloud API'),
 ('openstack', 'nova.api.openstack.wsgi', 'Cloud API'),
 ('openstack', 'nova.compute.claims', 'Cloud Compute'),
 ('openstack', 'nova.scheduler.host_manager', 'Cloud Compute'),
 ('openstack', 'oslo_service.periodic_task', 'Cloud Platform'),
 ('openstack', 'keystonemiddleware.auth_token', 'Cloud Identity')
) AS proposed(dataset, component, team)
WHERE NOT EXISTS (
 SELECT 1 FROM component_ownership existing
 WHERE existing.dataset = proposed.dataset AND existing.component = proposed.component
);
