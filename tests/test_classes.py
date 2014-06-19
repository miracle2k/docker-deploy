from deploylib.daemon.controller import canonical_definition


class TestServiceDef(object):
    """The service definition wrapper.
    """

    def test_deep_copy(self):
        """The service definition dict, when copied, is always a deepcopy."""
        _, d = canonical_definition('foo', {'env': {'FOO': 1}})
        d2 = d.copy()
        d['env']['NEW'] = 42
        assert not 'NEW' in d2['env']

    def test_with_image_key(self):
        # [Regression] image key is accepted as a regular, not an extra key
        _, d = canonical_definition('foo', {'image': 'bar'})
        assert not d['kwargs']

