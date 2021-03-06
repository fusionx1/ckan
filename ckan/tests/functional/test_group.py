import re

from nose.tools import assert_equal

from ckan.tests import setup_test_search_index
from ckan.plugins import SingletonPlugin, implements, IGroupController
from ckan import plugins
import ckan.model as model
from ckan.lib.create_test_data import CreateTestData
from ckan.logic import check_access, NotAuthorized

from pylons import config

from ckan.tests import *
from ckan.tests import setup_test_search_index
from base import FunctionalTestCase
from ckan.tests import search_related, is_search_supported


class MockGroupControllerPlugin(SingletonPlugin):
    implements(IGroupController)

    def __init__(self):
        from collections import defaultdict
        self.calls = defaultdict(int)

    def read(self, entity):
        self.calls['read'] += 1

    def create(self, entity):
        self.calls['create'] += 1

    def edit(self, entity):
        self.calls['edit'] += 1

    def authz_add_role(self, object_role):
        self.calls['authz_add_role'] += 1

    def authz_remove_role(self, object_role):
        self.calls['authz_remove_role'] += 1

    def delete(self, entity):
        self.calls['delete'] += 1

    def before_view(self, data_dict):
        self.calls['before_view'] += 1
        return data_dict


class TestGroup(FunctionalTestCase):

    @classmethod
    def setup_class(self):
        model.Session.remove()
        CreateTestData.create()

    @classmethod
    def teardown_class(self):
        model.repo.rebuild_db()

    def test_mainmenu(self):
        # the home page does a package search so have to skip this test if
        # search is not supported
        if not is_search_supported():
            from nose import SkipTest
            raise SkipTest("Search not supported")

        offset = url_for(controller='home', action='index')
        res = self.app.get(offset)
        assert 'Groups' in res, res
        assert 'Groups</a>' in res, res
        res = res.click(href='/group', index=0)
        assert "Dave's books" in res, res

    def test_index(self):
        offset = url_for(controller='group', action='index')
        res = self.app.get(offset)
        assert re.search('<h1(.*)>\s*Groups', res.body)
        groupname = 'david'
        group = model.Group.by_name(unicode(groupname))
        group_title = group.title
        group_packages_count = len(group.active_packages().all())
        group_description = group.description
        self.check_named_element(res, 'tr', group_title,
                                 group_packages_count,
                                 group_description)
        res = res.click(group_title)
        assert groupname in res

    def test_read_non_existent(self):
        name = u'group_does_not_exist'
        offset = url_for(controller='group', action='read', id=name)
        res = self.app.get(offset, status=404)

    def test_read_plugin_hook(self):
        plugin = MockGroupControllerPlugin()
        plugins.load(plugin)
        name = u'david'
        offset = url_for(controller='group', action='read', id=name)
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        assert plugin.calls['read'] == 1, plugin.calls
        plugins.unload(plugin)

    def test_read_and_authorized_to_edit(self):
        name = u'david'
        title = u'Dave\'s books'
        pkgname = u'warandpeace'
        offset = url_for(controller='group', action='read', id=name)
        res = self.app.get(offset, extra_environ={'REMOTE_USER': 'russianfan'})
        assert title in res, res
        assert 'edit' in res
        assert name in res

    def test_new_page(self):
        offset = url_for(controller='group', action='new')
        res = self.app.get(offset, extra_environ={'REMOTE_USER': 'russianfan'})
        assert 'Add A Group' in res, res


class TestGroupWithSearch(FunctionalTestCase):

    @classmethod
    def setup_class(self):
        setup_test_search_index()
        model.Session.remove()
        CreateTestData.create()

    @classmethod
    def teardown_class(self):
        model.repo.rebuild_db()

    def test_read(self):
        # Relies on the search index being available
        name = u'david'
        title = u'Dave\'s books'
        pkgname = u'warandpeace'
        group = model.Group.by_name(name)
        for group_ref in (group.name, group.id):
            offset = url_for(controller='group', action='read', id=group_ref)
            res = self.app.get(offset)
            main_res = self.main_div(res)
            assert title in res, res
            #assert 'edit' not in main_res, main_res
            assert 'Administrators' in res, res
            assert 'russianfan' in main_res, main_res
            assert name in res, res
            no_datasets_found = int(re.search('(\d*) datasets found',
                                    main_res).groups()[0])
            assert_equal(no_datasets_found, 2)
            pkg = model.Package.by_name(pkgname)
            res = res.click(pkg.title)
            assert '%s - Datasets' % pkg.title in res


class TestEdit(FunctionalTestCase):

    @classmethod
    def setup_class(self):
        setup_test_search_index()
        model.Session.remove()
        CreateTestData.create()
        self.groupname = u'david'
        self.packagename = u'testpkg'
        model.repo.new_revision()
        model.Session.add(model.Package(name=self.packagename))
        model.repo.commit_and_remove()


    @classmethod
    def teardown_class(self):
        model.Session.remove()
        model.repo.rebuild_db()
        model.Session.remove()

    def test_0_not_authz(self):
        offset = url_for(controller='group', action='edit', id=self.groupname)
        # 401 gets caught by repoze.who and turned into redirect
        res = self.app.get(offset, status=[302, 401])
        res = res.follow()
        assert res.request.url.startswith('/user/login')

    def test_2_edit(self):
        group = model.Group.by_name(self.groupname)
        offset = url_for(controller='group', action='edit', id=self.groupname)
        print offset
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        assert 'Edit: %s' % group.title in res, res

        form = res.forms['group-edit']
        titlefn = 'title'
        descfn = 'description'
        newtitle = 'xxxxxxx'
        newdesc = '''### Lots of stuff here

Ho ho ho
'''

        form[titlefn] = newtitle
        form[descfn] = newdesc
        pkg = model.Package.by_name(self.packagename)
        form['packages__2__name'] = pkg.name

        res = form.submit('save', status=302,
                          extra_environ={'REMOTE_USER': 'russianfan'})
        # should be read page
        # assert 'Groups - %s' % self.groupname in res, res

        model.Session.remove()
        group = model.Group.by_name(self.groupname)
        assert group.title == newtitle, group
        assert group.description == newdesc, group

        # now look at datasets
        assert len(group.active_packages().all()) == 3

    def test_3_edit_form_has_new_package(self):
        # check for dataset in autocomplete
        offset = url_for(controller='package', action='autocomplete', q='an')
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        assert 'annakarenina' in res, res
        assert not 'newone' in res, res
        model.repo.new_revision()
        pkg = model.Package(name=u'anewone')
        model.Session.add(pkg)
        model.repo.commit_and_remove()

        model.repo.new_revision()
        pkg = model.Package.by_name(u'anewone')
        user = model.User.by_name(u'russianfan')
        model.setup_default_user_roles(pkg, [user])
        model.repo.commit_and_remove()

        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        assert 'annakarenina' in res, res
        assert 'newone' in res

    def test_4_new_duplicate_package(self):
        prefix = ''

        # Create group
        group_name = u'testgrp4'
        CreateTestData.create_groups([{'name': group_name,
                                       'packages': [self.packagename]}],
                                     admin_user_name='russianfan')

        # Add same package again
        offset = url_for(controller='group', action='edit', id=group_name)
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        fv = res.forms['group-edit']
        fv['packages__1__name'] = self.packagename
        res = fv.submit('save', status=302,
                        extra_environ={'REMOTE_USER': 'russianfan'})
        res = res.follow()
        assert group_name in res, res
        model.Session.remove()

        # check package only added to the group once
        group = model.Group.by_name(group_name)
        pkg_names = [pkg.name for pkg in group.active_packages().all()]
        assert_equal(pkg_names, [self.packagename])

    def test_edit_plugin_hook(self):
        plugin = MockGroupControllerPlugin()
        plugins.load(plugin)
        offset = url_for(controller='group', action='edit', id=self.groupname)
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        form = res.forms['group-edit']
        group = model.Group.by_name(self.groupname)
        form['title'] = "huhuhu"
        res = form.submit('save', status=302,
                          extra_environ={'REMOTE_USER': 'russianfan'})
        assert plugin.calls['edit'] == 1, plugin.calls
        plugins.unload(plugin)

    def test_edit_image_url(self):
        group = model.Group.by_name(self.groupname)
        offset = url_for(controller='group', action='edit', id=self.groupname)
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})

        form = res.forms['group-edit']
        image_url = u'http://url.to/image_url'
        form['image_url'] = image_url
        res = form.submit('save', status=302,
                          extra_environ={'REMOTE_USER': 'russianfan'})

        model.Session.remove()
        group = model.Group.by_name(self.groupname)
        assert group.image_url == image_url, group

    def test_edit_change_name(self):
        group = model.Group.by_name(self.groupname)
        offset = url_for(controller='group', action='edit', id=self.groupname)
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        assert 'Edit: %s' % group.title in res, res

        def update_group(res, name, with_pkg=True):
            form = res.forms['group-edit']
            titlefn = 'title'
            descfn = 'description'
            newtitle = 'xxxxxxx'
            newdesc = '''### Lots of stuff here

    Ho ho ho
    '''
            form[titlefn] = newtitle
            form[descfn] = newdesc
            form['name'] = name
            if with_pkg:
                pkg = model.Package.by_name(self.packagename)
                form['packages__2__name'] = pkg.name

            res = form.submit('save', status=302,
                              extra_environ={'REMOTE_USER': 'russianfan'})
        update_group(res, self.groupname, True)
        update_group(res, 'newname', False)

        model.Session.remove()
        group = model.Group.by_name('newname')

        # We have the datasets in the DB, but we should also see that many
        # on the group read page.
        assert len(group.active_packages().all()) == 3

        offset = url_for(controller='group', action='read', id='newname')
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})

        ds = res.body
        ds = ds[ds.index('datasets') - 10: ds.index('datasets') + 10]
        assert '3 datasets found' in res, ds

        # reset the group to how we found it
        offset = url_for(controller='group', action='edit', id='newname')
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})

        update_group(res, self.groupname, True)

    def test_edit_non_existent(self):
        name = u'group_does_not_exist'
        offset = url_for(controller='group', action='edit', id=name)
        res = self.app.get(offset, status=404)

    def test_delete(self):
        group_name = 'deletetest'
        CreateTestData.create_groups([{'name': group_name,
                                       'packages': [self.packagename]}],
                                     admin_user_name='russianfan')

        group = model.Group.by_name(group_name)
        offset = url_for(controller='group', action='edit', id=group_name)
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        main_res = self.main_div(res)
        assert 'Edit: %s' % group.title in main_res, main_res
        assert 'value="active" selected' in main_res, main_res

        # delete
        form = res.forms['group-edit']
        form['state'] = 'deleted'
        res = form.submit('save', status=302,
                          extra_environ={'REMOTE_USER': 'russianfan'})

        group = model.Group.by_name(group_name)
        assert_equal(group.state, 'deleted')
        res = self.app.get(offset, status=302)
        res = res.follow()
        assert res.request.url.startswith('/user/login'), res.request.url


class TestNew(FunctionalTestCase):
    groupname = u'david'

    @classmethod
    def setup_class(self):
        model.Session.remove()
        CreateTestData.create()

        self.packagename = u'testpkg'
        model.repo.new_revision()
        model.Session.add(model.Package(name=self.packagename))
        model.repo.commit_and_remove()

    @classmethod
    def teardown_class(self):
        model.Session.remove()
        model.repo.rebuild_db()
        model.Session.remove()

    def test_1_not_authz(self):
        offset = url_for(controller='group', action='new')
        # 401 gets caught by repoze.who and turned into redirect
        res = self.app.get(offset, status=[302, 401])
        res = res.follow()
        assert res.request.url.startswith('/user/login')

    def test_2_new(self):
        prefix = ''
        group_name = u'testgroup'
        group_title = u'Test Title'
        group_description = u'A Description'

        # Open 'Add A Group' page
        offset = url_for(controller='group', action='new')
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        assert 'Add A Group' in res, res
        fv = res.forms['group-edit']
        assert fv[prefix + 'name'].value == '', fv.fields
        assert fv[prefix + 'title'].value == ''
        assert fv[prefix + 'description'].value == ''
        assert fv['packages__0__name'].value == '', \
            fv['Member--package_name'].value

        # Edit form
        fv[prefix + 'name'] = group_name
        fv[prefix + 'title'] = group_title
        fv[prefix + 'description'] = group_description
        pkg = model.Package.by_name(self.packagename)
        fv['packages__0__name'] = pkg.name
        res = fv.submit('save', status=302,
                        extra_environ={'REMOTE_USER': 'russianfan'})
        res = res.follow()
        assert '%s' % group_title in res, res

        model.Session.remove()
        group = model.Group.by_name(group_name)
        assert group.title == group_title, group
        assert group.description == group_description, group
        assert len(group.active_packages().all()) == 1
        pkg = model.Package.by_name(self.packagename)
        assert group.active_packages().all() == [pkg]

    def test_3_new_duplicate_group(self):
        prefix = ''

        # Create group
        group_name = u'testgrp1'
        offset = url_for(controller='group', action='new')
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        assert 'Add A Group' in res, res
        fv = res.forms['group-edit']
        assert fv[prefix + 'name'].value == '', fv.fields
        fv[prefix + 'name'] = group_name
        res = fv.submit('save', status=302,
                        extra_environ={'REMOTE_USER': 'russianfan'})
        res = res.follow()
        assert group_name in res, res
        model.Session.remove()

        # Create duplicate group
        group_name = u'testgrp1'
        offset = url_for(controller='group', action='new')
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        assert 'Add A Group' in res, res
        fv = res.forms['group-edit']
        assert fv[prefix + 'name'].value == '', fv.fields
        fv[prefix + 'name'] = group_name
        res = fv.submit('save', status=200,
                        extra_environ={'REMOTE_USER': 'russianfan'})
        assert 'Group name already exists' in res, res
        self.check_tag(res, '<form', 'has-errors')
        assert 'class="field_error"' in res, res

    def test_new_plugin_hook(self):
        plugin = MockGroupControllerPlugin()
        plugins.load(plugin)
        offset = url_for(controller='group', action='new')
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        form = res.forms['group-edit']
        form['name'] = "hahaha"
        form['title'] = "huhuhu"
        res = form.submit('save', status=302,
                          extra_environ={'REMOTE_USER': 'russianfan'})
        assert plugin.calls['create'] == 1, plugin.calls
        plugins.unload(plugin)

    def test_new_bad_param(self):
        offset = url_for(controller='group', action='new',
                         __bad_parameter='value')
        res = self.app.post(offset, {'save': '1'},
                            extra_environ={'REMOTE_USER': 'russianfan'},
                            status=400)
        assert 'Integrity Error' in res.body


class TestRevisions(FunctionalTestCase):
    @classmethod
    def setup_class(self):
        model.Session.remove()
        CreateTestData.create()
        self.name = u'revisiontest1'

        # create pkg
        self.description = [u'Written by Puccini', u'Written by Rossini',
                            u'Not written at all', u'Written again',
                            u'Written off']
        rev = model.repo.new_revision()
        self.grp = model.Group(name=self.name)
        self.grp.description = self.description[0]
        model.Session.add(self.grp)
        model.setup_default_user_roles(self.grp)
        model.repo.commit_and_remove()

        # edit pkg
        for i in range(5)[1:]:
            rev = model.repo.new_revision()
            grp = model.Group.by_name(self.name)
            grp.description = self.description[i]
            model.repo.commit_and_remove()

        self.grp = model.Group.by_name(self.name)

    @classmethod
    def teardown_class(self):
        self.purge_packages([self.name])
        model.repo.rebuild_db()

    def test_0_read_history(self):
        offset = url_for(controller='group', action='history',
                         id=self.grp.name)
        res = self.app.get(offset)
        main_res = self.main_div(res)
        assert self.grp.name in main_res, main_res
        assert 'radio' in main_res, main_res
        latest_rev = self.grp.all_revisions[0]
        oldest_rev = self.grp.all_revisions[-1]
        first_radio_checked_html = \
            '<input checked="checked" id="selected1_%s"' % \
            latest_rev.revision_id
        assert first_radio_checked_html in main_res, '%s %s' % \
            (first_radio_checked_html, main_res)
        last_radio_checked_html = \
            '<input checked="checked" id="selected2_%s"' % \
            oldest_rev.revision_id
        assert last_radio_checked_html in main_res, '%s %s' % \
            (last_radio_checked_html, main_res)

    def test_1_do_diff(self):
        offset = url_for(controller='group', action='history',
                         id=self.grp.name)
        res = self.app.get(offset)
        form = res.forms['group-revisions']
        res = form.submit()
        res = res.follow()
        main_res = self.main_div(res)
        assert 'form-errors' not in main_res.lower(), main_res
        assert 'Revision Differences' in main_res, main_res
        assert self.grp.name in main_res, main_res
        assert "<tr><td>description</td><td><pre>- Written by Puccini\n+" + \
               " Written off</pre></td></tr>" in main_res, main_res

    def test_2_atom_feed(self):
        offset = url_for(controller='group', action='history',
                         id=self.grp.name)
        offset = "%s?format=atom" % offset
        res = self.app.get(offset)
        assert '<feed' in res, res
        assert 'xmlns="http://www.w3.org/2005/Atom"' in res, res
        assert '</feed>' in res, res


class TestOrganizationGroup(FunctionalTestCase):

    @classmethod
    def setup_class(self):
        model.Session.remove()
        CreateTestData.create(auth_profile='publisher')

    @classmethod
    def teardown_class(self):
        model.repo.rebuild_db()

    def test_index(self):
        from pylons import config
        from nose.exc import SkipTest
        if config.get('ckan.auth.profile', '') != 'publisher':
            raise SkipTest('Publisher auth profile not enabled')

        offset = url_for(controller='group', action='index')
        res = self.app.get(offset)
        assert '<h1 class="page_heading">Groups' in res, res
        groupname = 'david'
        group = model.Group.by_name(unicode(groupname))
        group_title = group.title
        group_packages_count = len(group.active_packages().all())
        group_description = group.description
        self.check_named_element(res, 'tr', group_title,
                                 group_packages_count,
                                 group_description)
        res = res.click(group_title)
        assert groupname in res
        assert 'organization' == group.type, group.type

    def test_read(self):
        from pylons import config
        from nose.exc import SkipTest
        if config.get('ckan.auth.profile', '') != 'publisher':
            raise SkipTest('Publisher auth profile not enabled')

        # Relies on the search index being available
        setup_test_search_index()
        name = u'david'
        title = u'Dave\'s books'
        pkgname = u'warandpeace'
        group = model.Group.by_name(name)
        assert 'organization' == group.type
        for group_ref in (group.name, group.id):
            offset = url_for(controller='group', action='read', id=group_ref)
            res = self.app.get(offset)
            main_res = self.main_div(res)
            assert title in res, res
            assert 'Administrators' in res, res
            assert 'russianfan' in main_res, main_res
            assert name in res, res
            assert '0 datasets found.' in self.strip_tags(main_res), main_res

    def test_read_and_not_authorized_to_edit(self):
        from pylons import config
        from nose.exc import SkipTest
        if config.get('ckan.auth.profile', '') != 'publisher':
            raise SkipTest('Publisher auth profile not enabled')

        name = u'david'
        title = u'Dave\'s books'
        pkgname = u'warandpeace'
        offset = url_for(controller='group', action='edit', id=name)
        res = self.app.get(offset,  status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})


class TestPublisherEdit(FunctionalTestCase):

    @classmethod
    def setup_class(self):
        from ckan.tests.mock_publisher_auth import MockPublisherAuth
        self.auth = MockPublisherAuth()

        model.Session.remove()
        CreateTestData.create(auth_profile='publisher')
        self.groupname = u'david'
        self.packagename = u'testpkg'
        model.repo.new_revision()
        model.Session.add(model.Package(name=self.packagename))
        model.repo.commit_and_remove()

    @classmethod
    def teardown_class(self):
        model.Session.remove()
        model.repo.rebuild_db()
        model.Session.remove()

    def test_0_not_authz(self):
        from pylons import config
        from nose.exc import SkipTest
        if config.get('ckan.auth.profile', '') != 'publisher':
            raise SkipTest('Publisher auth profile not enabled')

        offset = url_for(controller='group', action='edit', id=self.groupname)
        # 401 gets caught by repoze.who and turned into redirect
        res = self.app.get(offset, status=[302, 401])
        res = res.follow()
        assert res.request.url.startswith('/user/login')

    def test_2_edit(self):
        from pylons import config
        from nose.exc import SkipTest
        if config.get('ckan.auth.profile', '') != 'publisher':
            raise SkipTest('Publisher auth profile not enabled')

        group = model.Group.by_name(self.groupname)
        offset = url_for(controller='group', action='edit', id=self.groupname)
        user = model.User.get('russianfan')

        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        assert 'Edit: %s' % group.title in res, res

        form = res.forms['group-edit']
        titlefn = 'title'
        descfn = 'description'
        newtitle = 'xxxxxxx'
        newdesc = '''### Lots of stuff here

Ho ho ho
'''

        form[titlefn] = newtitle
        form[descfn] = newdesc
        pkg = model.Package.by_name(self.packagename)
        form['packages__2__name'] = pkg.name

        res = form.submit('save', status=302,
                          extra_environ={'REMOTE_USER': 'russianfan'})
        # should be read page
        # assert 'Groups - %s' % self.groupname in res, res

        model.Session.remove()
        group = model.Group.by_name(self.groupname)
        assert group.title == newtitle, group
        assert group.description == newdesc, group

        # now look at datasets
        assert len(group.active_packages().all()) == 3

    def test_3_edit_form_has_new_package(self):
        # check for dataset in autocomplete
        offset = url_for(controller='package', action='autocomplete', q='an')
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        assert 'annakarenina' in res, res
        assert not 'newone' in res, res
        model.repo.new_revision()
        pkg = model.Package(name=u'anewone')
        model.Session.add(pkg)
        model.repo.commit_and_remove()

        model.repo.new_revision()
        pkg = model.Package.by_name(u'anewone')
        user = model.User.by_name(u'russianfan')
        model.setup_default_user_roles(pkg, [user])
        model.repo.commit_and_remove()

        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        assert 'annakarenina' in res, res
        assert 'newone' in res

    def test_4_new_duplicate_package(self):
        prefix = ''

        # Create group
        group_name = u'testgrp4'
        CreateTestData.create_groups([{'name': group_name,
                                       'packages': [self.packagename]}],
                                     admin_user_name='russianfan')

        # Add same package again
        offset = url_for(controller='group', action='edit', id=group_name)
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        fv = res.forms['group-edit']
        fv['packages__1__name'] = self.packagename
        res = fv.submit('save', status=302,
                        extra_environ={'REMOTE_USER': 'russianfan'})
        res = res.follow()
        assert group_name in res, res
        model.Session.remove()

        # check package only added to the group once
        group = model.Group.by_name(group_name)
        pkg_names = [pkg.name for pkg in group.active_packages().all()]
        assert_equal(pkg_names, [self.packagename])

    def test_edit_plugin_hook(self):
        plugin = MockGroupControllerPlugin()
        plugins.load(plugin)
        offset = url_for(controller='group', action='edit', id=self.groupname)
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        form = res.forms['group-edit']
        group = model.Group.by_name(self.groupname)
        form['title'] = "huhuhu"
        res = form.submit('save', status=302,
                          extra_environ={'REMOTE_USER': 'russianfan'})
        assert plugin.calls['edit'] == 1, plugin.calls
        plugins.unload(plugin)

    def test_edit_non_auth(self):
        offset = url_for(controller='group', action='edit', id=self.groupname)
        res = self.app.get(offset, status=[302, 401],
                           extra_environ={'REMOTE_USER': 'non-existent'})

    def test_edit_fail_auth(self):
        context = {'group': model.Group.by_name(self.groupname),
                   'model': model, 'user': 'russianfan'}
        try:
            if self.auth.check_access('group_update', context, {}):
                assert False, "Check access said incorrectly said allowed"
        except NotAuthorized, e:
            pass  # Do nothing as this is what we expected

    def test_edit_success_auth(self):
        userobj = model.User.get('russianfan')
        grp = model.Group.by_name(self.groupname)

        def gg(*args, **kwargs):
            return [grp]
        model.User.get_groups = gg

        context = {'group': grp, 'model': model, 'user': 'russianfan'}
        try:
            self.auth.check_access('group_update', context, {})
        except NotAuthorized, e:
            assert False, "The user should have access"

    def test_delete(self):
        group_name = 'deletetest'
        CreateTestData.create_groups([{'name': group_name,
                                       'packages': [self.packagename]}],
                                     admin_user_name='russianfan')

        group = model.Group.by_name(group_name)
        offset = url_for(controller='group', action='edit', id=group_name)
        res = self.app.get(offset, status=200,
                           extra_environ={'REMOTE_USER': 'russianfan'})
        main_res = self.main_div(res)
        assert 'Edit: %s' % group.title in main_res, main_res
        assert 'value="active" selected' in main_res, main_res

        # delete
        form = res.forms['group-edit']
        form['state'] = 'deleted'
        res = form.submit('save', status=302,
                          extra_environ={'REMOTE_USER': 'russianfan'})

        group = model.Group.by_name(group_name)
        assert_equal(group.state, 'deleted')
        res = self.app.get(offset, status=302)
        res = res.follow()
        assert res.request.url.startswith('/user/login'), res.request.url
