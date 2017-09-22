import collections
import contextlib
import enum
import json
import os
from xml.sax import saxutils
import sys


class MarkusTestSpecs(collections.MutableMapping):

    # special keys
    MATRIX_KEY = 'matrix'
    MATRIX_NODATA_KEY = 'nodata'
    MATRIX_NONTEST_KEY = 'extra'
    FEEDBACK_FILE_KEY = 'feedback_file'
    DATA_FILES_SEPARATOR = ','

    def __init__(self, path_to_specs=None):
        if path_to_specs is None:  # try to find specs automagically
            path_to_specs = sys.executable.replace('venvs', 'specs').replace('bin/python3', 'specs.json')
        with open(path_to_specs, 'r') as specs_open:
            self._specs = json.loads(specs_open.read())
        if MarkusTestSpecs.MATRIX_KEY not in self._specs:
            self._specs[MarkusTestSpecs.MATRIX_KEY] = {}
        if MarkusTestSpecs.FEEDBACK_FILE_KEY not in self._specs:
            self._specs[MarkusTestSpecs.FEEDBACK_FILE_KEY] = None

    def _setitem(self, key, value):
        self._specs[key] = value

    def _set_points(self, _, value):
        """
        SPECS['points'] = {'test1': {'data1': points11, 'data2': points12},
                           'test2': {'data1': points21, 'data2': points22}}
        Assigns points to the passed tests and datasets, creating them if they don't exist yet.
        """
        for test_file, data_files in value.items():
            if test_file in self.matrix:
                for data_file, points in data_files.items():
                    self.matrix[test_file][data_file] = points
            else:
                self.matrix[test_file] = data_files

    def _set_test_points(self, _, value):
        """
        SPECS['test_points'] = {'test1': points1, 'test2': points2}
        Assigns points to all datasets of the passed tests, creating the tests if they don't exist yet.
        """
        for test_file, points in value.items():
            data_files = self.matrix.setdefault(test_file, {MarkusTestSpecs.MATRIX_NODATA_KEY: {}})
            for data_file in data_files:
                if data_file == MarkusTestSpecs.MATRIX_NONTEST_KEY:
                    continue
                self.matrix[test_file][data_file] = points

    def _set_data_points(self, _, value):
        """
        SPECS['data_points'] = {'data1': points1, 'data2': points2}
        Assigns points to all existing tests that use the passed datasets, does nothing for tests that don't use them.
        """
        for test_file in self.matrix:
            for data_file, points in value.items():
                if data_file not in self.matrix[test_file]:
                    continue
                self.matrix[test_file][data_file] = points

    def _set_all_points(self, _, points):
        """
        SPECS['all_points'] = points
        Assigns points to all existing tests and datasets.
        """
        for test_file, data_files in self.matrix.items():
            for data_file in data_files:
                if data_file == MarkusTestSpecs.MATRIX_NONTEST_KEY:
                    continue
                self.matrix[test_file][data_file] = points

    def __setitem__(self, key, value):
        switch = {'points': self._set_points, 'test_points': self._set_test_points,
                  'data_points': self._set_data_points, 'all_points': self._set_all_points}
        setter = switch.get(key, self._setitem)
        setter(key, value)

    def __getitem__(self, key):
        return self._specs[key]

    def __delitem__(self, key):
        del self._specs[key]

    def __iter__(self):
        return iter(self._specs)

    def __len__(self):
        return len(self._specs)

    @property
    def matrix(self):
        return self[MarkusTestSpecs.MATRIX_KEY]

    @property
    def feedback_file(self):
        return self[MarkusTestSpecs.FEEDBACK_FILE_KEY]

    @property
    def test_files(self):
        return self.matrix.keys()


class MarkusTester:

    def __init__(self, specs):
        self.specs = specs

    def create_test(self, test_file, data_files, test_data_config, test_extra, feedback_open):
        # TODO Make it more elegant using a factory pattern, and add all global test configs
        return MarkusTest(test_file, data_files, test_data_config, test_extra, feedback_open)

    @staticmethod
    def error_all(message, points_total=None):
        """
        Err all tests of this tester with a single message.
        :param message: The error message.
        :param points_total: The total points the tests could award, must be an integer > 0. Can be None if unknown.
        :return The formatted erred tests.
        """
        return MarkusTest.format_result(test_name='All tests', status=MarkusTest.Status.ERROR, points_awarded=0,
                                        output=message, points_total=points_total)

    def run(self):
        try:
            with contextlib.ExitStack() as stack:
                feedback_open = (stack.enter_context(open(self.specs.feedback_file, 'w'))
                                 if self.specs.feedback_file is not None
                                 else None)
                for test_file in sorted(self.specs.test_files):
                    test_extra = self.specs.matrix[test_file].get(MarkusTestSpecs.MATRIX_NONTEST_KEY)
                    for data_files in sorted(self.specs.matrix[test_file].keys()):
                        if data_files == MarkusTestSpecs.MATRIX_NONTEST_KEY:
                            continue
                        points = self.specs.matrix[test_file][data_files]
                        if MarkusTestSpecs.DATA_FILES_SEPARATOR in data_files:
                            data_files = data_files.split(MarkusTestSpecs.DATA_FILES_SEPARATOR)
                        else:
                            data_files = [data_files]
                        test = self.create_test(test_file, data_files, points, test_extra, feedback_open)
                        xml = test.run()
                        print(xml)
        except Exception as e:
            print(MarkusTester.error_all(message=str(e)))


class MarkusTest:

    class Status(enum.Enum):
        PASS = 'pass'
        PARTIAL = 'partial'
        FAIL = 'fail'
        ERROR = 'error'

    def __init__(self, test_file, data_files, points, test_extra, feedback_open=None):
        self.test_file = test_file
        self.test_name = os.path.splitext(test_file)[0]
        self.data_files = data_files
        self.data_name = MarkusTestSpecs.DATA_FILES_SEPARATOR.join(
                             [os.path.splitext(data_file)[0] for data_file in data_files])
        self.test_data_name = '{} + {}'.format(self.test_name, self.data_name)
        self.points = points  # TODO Use a default or disable if not set?
        if isinstance(self.points, dict):
            self.points_total = max(self.points.values())
        else:
            self.points_total = self.points
        if self.points_total <= 0:
            raise ValueError('The test total points must be > 0')
        self.test_extra = test_extra
        self.feedback_open = feedback_open

    @staticmethod
    def format_result(test_name, status, points_awarded, output, points_total=None):
        """
        Formats a test result as expected by Markus.
        :param test_name: The test name
        :param status: A member of MarkusTest.Status.
        :param points_awarded: The points awarded by the test, must be an integer >= 0 and <= test total points.
        :param output: The test output.
        :param points_total: The total points the test could award, must be an integer > 0. Can be None if unknown.
        :return The formatted test result.
        """
        if points_total is not None and points_total <= 0:
            raise ValueError('The test total points must be > 0')
        if points_awarded < 0:
            raise ValueError('The test points awarded must be >= 0')
        if points_total is not None and points_awarded > points_total:
            raise ValueError('The test points awarded must be <= test total points')
        output_escaped = saxutils.escape(output.replace('\x00', ''), entities={"'": '&apos;'})
        if points_total is None:
            name = test_name
        else:
            name = '[{}/{}] {}'.format(points_awarded, points_total, test_name)
        return '''
        <test>
            <name>{}</name>
            <input></input>
            <expected></expected>
            <actual>{}</actual>
            <marks_earned>{}</marks_earned>
            <status>{}</status>
        </test>'''.format(name, output_escaped, points_awarded, status.value)

    def format(self, status, points_awarded, output):
        """
        Formats the result of this test as expected by Markus.
        :param status: A member of MarkusTest.Status.
        :param points_awarded: The points awarded by the test, must be an integer >= 0 and <= test total points.
        :param output: The test output.
        :return The formatted test result.
        """
        return MarkusTest.format_result(self.test_data_name, status, points_awarded, output, self.points_total)

    def add_feedback(self, status, feedback='', oracle_solution=None, test_solution=None):
        """
        Adds the feedback of this test to the feedback file.
        :param status: A member of MarkusTest.Status.
        :param feedback: The feedback, can be None.
        :param oracle_solution: The expected solution, can be None.
        :param test_solution: The test solution, can be None.
        """
        # TODO Reconcile with format: return both, or print both
        if self.feedback_open is None:
            raise ValueError('No feedback file enabled')
        self.feedback_open.write('========== {}: {} ==========\n\n'.format(self.test_data_name, status.value.upper()))
        if feedback:
            self.feedback_open.write('## Feedback: {}\n\n'.format(feedback))
        if status != MarkusTest.Status.PASS:
            if oracle_solution:
                self.feedback_open.write('## Expected Solution:\n\n')
                self.feedback_open.write(oracle_solution)
            if test_solution:
                self.feedback_open.write('## Your Solution:\n\n')
                self.feedback_open.write(test_solution)
        self.feedback_open.write('\n')

    def passed(self, message=''):
        """
        Passes this test with the test total points awarded. If a feedback file is enabled, adds feedback to it.
        :param message: An optional message, will be shown as test output.
        :return The formatted passed test.
        """
        result = self.format(status=MarkusTest.Status.PASS, points_awarded=self.points_total, output=message)
        if self.feedback_open:
            self.add_feedback(status=MarkusTest.Status.PASS)
        return result

    def partially_passed(self, points_awarded, message, oracle_solution=None, test_solution=None):
        """
        Partially passes this test with some points awarded. If the points are <= 0 this test is failed with 0 points
        awarded, if the points are >= test total points this test is passed with the test total points awarded. If a
        feedback file is enabled, adds feedback to it.
        :param points_awarded: The points awarded by the test.
        :param message: The message explaining why the test was not fully passed, will be shown as test output.
        :param oracle_solution: The optional correct solution to be added to the feedback file.
        :param test_solution: The optional student solution to be added to the feedback file.
        :return The formatted partially passed test.
        """
        if points_awarded <= 0:
            return self.failed(message, oracle_solution, test_solution)
        if points_awarded >= self.points_total:
            return self.passed(message)
        result = self.format(status=MarkusTest.Status.PARTIAL, points_awarded=points_awarded, output=message)
        if self.feedback_open:
            self.add_feedback(status=MarkusTest.Status.PARTIAL, feedback=message, oracle_solution=oracle_solution,
                              test_solution=test_solution)
        return result

    def failed(self, message, oracle_solution=None, test_solution=None):
        """
        Fails this test with 0 points awarded. If a feedback file is enabled, adds feedback to it.
        :param message: The failure message, will be shown as test output.
        :param oracle_solution: The optional correct solution to be added to the feedback file.
        :param test_solution: The optional student solution to be added to the feedback file.
        :return The formatted failed test.
        """
        result = self.format(status=MarkusTest.Status.FAIL, points_awarded=0, output=message)
        if self.feedback_open:
            self.add_feedback(status=MarkusTest.Status.FAIL, feedback=message, oracle_solution=oracle_solution,
                              test_solution=test_solution)
        return result

    def error(self, message):
        """
        Err this test. If a feedback file is enabled, adds feedback to it.
        :param message: The error message, will be shown as test output.
        :return The formatted erred test.
        """
        result = self.format(status=MarkusTest.Status.ERROR, points_awarded=0, output=message)
        if self.feedback_open:
            self.add_feedback(status=MarkusTest.Status.ERROR, feedback=message)
        return result

    def run(self):
        """
        Runs this test.
        :return The formatted test.
        """
        raise NotImplementedError
