"""The cuts for science run 0

This includes all current definitions of the cuts for the first science run
"""

# -*- coding: utf-8 -*-
import inspect
import os
import pytz
import pickle  # noqa

import numpy as np
from pax import units

from scipy.stats import chi2

from lax.lichen import Lichen, RangeLichen, ManyLichen, StringLichen
from lax import __version__ as lax_version

# Store the directory of our data files
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))),
                        '..', 'data')


class AllEnergy(ManyLichen):
    """Cuts applicable for low and high energy (gammas)

    This is a subset mostly of the low energy cuts.
    """
    version = lax_version

    def __init__(self):
        self.lichen_list = [
            FiducialZOptimized(),
            InteractionExists(),
            S2Threshold(),
            InteractionPeaksBiggest(),
            CS2AreaFractionTop(),
            S2SingleScatter(),
            S2Width(),
            DAQVeto(),
            S1SingleScatter(),
            S2PatternLikelihood(),
            KryptonMisIdS1(),
            Flash(),
            PosDiff(),
            SingleElectronS2s()
        ]


class LowEnergyRn220(AllEnergy):
    """Select Rn220 events with cs1<200

    This is the list that we use for the Rn220 data to calibrate ER in the
    region of interest.
    """

    def __init__(self):
        AllEnergy.__init__(self)

        # Customize cuts for calibration data
        for idx, lichen in enumerate(self.lichen_list):

            # Replaces InteractionExists with energy cut (tighter)
            if lichen.name() == "CutInteractionExists":
                self.lichen_list[idx] = S1LowEnergyRange()

            # Use a simpler single scatter cut for LowE
            if lichen.name() == "CutS2SingleScatter":
                self.lichen_list[idx] = S2SingleScatterSimple()

        # Add additional LowE cuts (that may not be tuned at HighE yet)
        self.lichen_list += [
            S1PatternLikelihood(),
            S1MaxPMT(),
            S1AreaFractionTop(),
            S1Width()
        ]

        # Add injection-position cuts (not for AmBe)
        self.lichen_list += [
            S1AreaUpperInjectionFraction(),
            S1AreaLowerInjectionFraction()
        ]


class LowEnergyBackground(LowEnergyRn220):
    """Select background events with cs1<200

    This is the list that we'll use for the actual DM search. Additionally to the
    LowEnergyAmBe list it contains the PreS2Junk, S2Tails, and MuonVeto
    """

    def __init__(self):
        LowEnergyRn220.__init__(self)

        # Add cuts specific to background only
        self.lichen_list += [
            PreS2Junk(),
            S2Tails(),  # Only for LowE background (#88)
            MuonVeto()
        ]


class LowEnergyAmBe(LowEnergyRn220):
    """Select AmBe events with cs1<200 with appropriate cuts

    It is the same as the LowEnergyRn220 cuts, except injection-related cuts
    """

    def __init__(self):
        LowEnergyRn220.__init__(self)

        # Remove cuts not applicable to AmBe
        self.lichen_list = [lichen for lichen in self.lichen_list
                            if "InjectionFraction" not in lichen.name()]


class DAQVeto(ManyLichen):
    """Check if DAQ busy or HE veto

    Make sure no DAQ vetos happen during your event. This
    automatically checks both busy and high-energy vetos.
    Also makes sure last BUSY type is 'off' and cuts
    last 21 seconds of each run.

    Requires Proximity minitrees.

    https://xecluster.lngs.infn.it/dokuwiki/doku.php?id=xenon:xenon1t:analysis:firstresults:daqandnoise

    Contact: Daniel Coderre <daniel.coderre@lhep.unibe.ch>
    """
    version = 1

    def __init__(self):
        self.lichen_list = [self.EndOfRunCheck(),
                            self.BusyTypeCheck(),
                            self.BusyCheck(),
                            self.HEVCheck()]

    class EndOfRunCheck(Lichen):
        """Check that the event does not come in the last 21 seconds of the run
        """

        def _process(self, df):
            import hax          # noqa
            if not len(hax.config):
                # User didn't init hax yet... let's do it now
                hax.init()

            # Get the end times for each run
            # The datetime -> timestamp logic here is the same as in the pax event builder
            run_numbers = np.unique(df.run_number.values)
            run_end_times = [int(q.replace(tzinfo=pytz.utc).timestamp() * int(1e9))
                             for q in hax.runs.get_run_info(run_numbers.tolist(), 'end')]
            run_end_times = {run_numbers[i]: run_end_times[i]
                             for i in range(len(run_numbers))}

            # Pass events that occur before (end time - 21 sec) of the run they are in
            df.loc[:, self.name()] = df.apply(lambda row: row['event_time'] <
                                              run_end_times[row['run_number']] - 21e9, axis=1)
            return df

    class BusyTypeCheck(Lichen):
        """Ensure that the last busy type (if any) is OFF
        """

        def _process(self, df):
            df.loc[:, self.name()] = ((~(df['previous_busy_on'] < 60e9)) |
                                      (df['previous_busy_off'] <
                                       df['previous_busy_on']))
            return df

    class BusyCheck(Lichen):
        """Check if the event contains a BUSY veto trigger
        """

        def _process(self, df):
            df.loc[:, self.name()] = (abs(df['nearest_busy']) >
                                      df['event_duration'] / 2)
            return df

    class HEVCheck(Lichen):
        """Check if the event contains a HE veto trigger
        """

        def _process(self, df):
            df.loc[:, self.name()] = (abs(df['nearest_hev']) >
                                      df['event_duration'] / 2)
            return df


class S2Tails(Lichen):
    """Check if event is in a tail of a previous S2

    Requires S2Tail minitrees.

    https://xecluster.lngs.infn.it/dokuwiki/doku.php?id=xenon:xenon1t:analysis:subgroup:wimphysics:s2_tails_sr0

    Contact: Daniel Coderre <daniel.coderre@lhep.unibe.ch>
    """
    version = 0

    def _process(self, df):
        df.loc[:, self.name()] = ((~(df['s2_over_tdiff'] >= 0)) |
                                  (df['s2_over_tdiff'] < 0.04))
        return df


class FiducialCylinder1T_TPF2dFDC(StringLichen):
    """Fiducial volume cut.

    The fidicual volume cut defines the region in depth and radius that we
    trust and use for the exposure. This is the region where the background
    distribution is flat.

    This version of the cut is based pax v6.4 bg run 0 data. See the
    note first results fiducial volume note for the study of the definition.

    (Used to be "FiducialCylinder1T" version 4.)

    Contact: Sander breur <sanderb@nikhef.nl>

    """
    version = 4
    string = "(-92.9 < z) & (z < -9) & (sqrt(x*x + y*y) < 36.94)"

    def pre(self, df):
        df.loc[:, 'r'] = np.sqrt(df['x'] * df['x'] + df['y'] * df['y'])
        return df


class FiducialCylinder1T(StringLichen):
    """Fiducial volume cut using NN 3D FDC instead of TPF 2D FDC above.

    Temporary/under development, for preliminary comparisons to
    FiducialCylinder1p3T below.

    """
    version = 5
    string = "(-92.9 < z_3d_nn) & (z_3d_nn < -9) & (r_3d_nn < 36.94)"


class FiducialCylinder1p3T(StringLichen):
    """Larger fiducial volume cut for benchmarking and development.

    Using new 3D FDC positions. Tested in e.g. following note:

    https://xe1t-wiki.lngs.infn.it/doku.php?id=xenon:kazama:ambe_ng_comparison:performance_check_ng_ambe

    """
    version = 0
    string = "(-92.9 < z_3d_nn) & (z_3d_nn < -9) & (r_3d_nn < 41.26)"


class FiducialZOptimized(StringLichen):
    """Z-optimized FV cut based on keeping expected rate variation within 10% threshold within each
    R slice, i.e. ~uniform in Z accounting for all backgrounds models.

    This first version is a bit rough and may be improved by understanding the underlying BG KDE
    and errors better.

    https://xe1t-wiki.lngs.infn.it/doku.php?id=xenon:xenon1t:analysis:sciencerun1:summary_fiducial_volume_v4
    """
    version = 4
    string = "(-94 < z_3d_nn) & (z_3d_nn < -8) & (r_3d_nn < 42.8387) & \
              (z_3d_nn < -2.63725 - 0.00946597*r_3d_nn*r_3d_nn) & \
              (z_3d_nn > -158.173 + 0.0456094*r_3d_nn*r_3d_nn)"


class FiducialInnerEgg(ManyLichen):
    """Inner-most clean yolk volume optimized against radiogenic neutron position distribution

    https://xe1t-wiki.lngs.infn.it/doku.php?id=xenon:xenon1t:mcfate:inner_volume_optimization_v2

    Contact: Qing Lin
    """
    version = 0

    def __init__(self):
        self.lichen_list = [self.FiducialInnerEggUpper(),
                            self.FiducialInnerEggLower(),
                            self.FiducialInnerEggEdge()]

    class FiducialInnerEggUpper(StringLichen):
        """Top part of egg
        """
        string = "(z_3d_nn < -49.43) | ( ((z_3d_nn+49.43)/36.35)**2.43474462 + (r_3d_nn*r_3d_nn/1367)**2.43474462 < 1.)"

    class FiducialInnerEggLower(StringLichen):
        """Bottom part of egg
        """
        string = "(z_3d_nn > -55.28) | ( (-(z_3d_nn+55.28)/26.24)**2.00197758 + (r_3d_nn*r_3d_nn/1365)**2.00197758 < 1.)"

    class FiducialInnerEggEdge(StringLichen):
        """Hard radial cut on currently defined bin edge
        """
        string = "r_3d_nn < 34.5903754"


FV_CONFIGS = [
    # Mass (kg), (z0, vz, p, vr2)
    (1000, (-57.58, 31.25, 4.20, 1932.53)),
    (1025, (-57.29, 31.65, 3.71, 1987.85)),
    (1050, (-62.25, 33.89, 3.08, 1969.68)),
    (1075, (-59.73, 35.58, 2.97, 1938.27)),
    (1100, (-58.36, 36.97, 2.67, 1951.06)),
    (1125, (-58.57, 37.36, 2.78, 1953.64)),
    (1150, (-58.71, 37.37, 3.25, 1934.94)),
    (1175, (-57.35, 38.17, 3.14, 1944.21)),
    (1200, (-56.44, 39.23, 2.88, 1961.09)),
    (1225, (-55.81, 40.30, 2.80, 1969.58)),
    (1250, (-55.44, 40.70, 3.21, 1936.89)),
    (1275, (-54.62, 41.19, 3.29, 1937.40)),
    (1300, (-54.04, 42.08, 2.56, 2041.03)),
    (1325, (-53.31, 42.52, 2.85, 2005.24)),
    (1350, (-51.63, 43.64, 3.15, 1949.59)),
    (1375, (-51.85, 44.07, 2.87, 2003.40)),
    (1400, (-52.22, 43.88, 3.88, 1949.48)),
    (1425, (-50.87, 45.22, 2.75, 2046.11)),
    (1450, (-51.66, 43.60, 3.58, 2053.80)),
    (1475, (-51.99, 43.92, 3.88, 2044.43)),
    (1500, (-52.50, 43.69, 4.31, 2059.53)),
    (1525, (-51.51, 44.67, 3.68, 2093.78)),
    (1550, (-51.13, 45.04, 3.98, 2088.21)),
    (1575, (-49.44, 46.67, 3.43, 2091.66)),
    (1600, (-50.15, 45.95, 3.77, 2126.11)),
    (1625, (-50.06, 45.99, 4.32, 2119.37)),
    (1650, (-50.16, 45.95, 4.67, 2137.15)),
    (1675, (-49.10, 47.05, 4.53, 2128.00)),
    (1700, (-49.54, 46.51, 6.10, 2129.72)),
]


class FiducialTestEllips(StringLichen):
    """TESTFiducial volume cut using NN 3D FDC.
    Temporary/under development, for preliminary
    comparisons between the different masses. For every mass
    in the fv_config keys a FiducialTestEllips<mass> is made.
    For more info on the construction of the FV see:
    https://xe1t-wiki.lngs.infn.it/doku.php?id=xenon:xenon1t:analysis:sciencerun1:fiducial_volume:optimized_ellips
    sanderb@nikhef.nl
    """
    version = 1
    parameter_symbols = tuple('z0 vz p vr2'.split())
    parameter_values = None   # Will be tuple of parameter values
    string = "((( (((z_3d_nn-@z0)**2)**0.5) /@vz)**@p)+ (r_3d_nn**2/@vr2)**@p) < 1"

    def _process(self, df):
        bla = dict(zip(self.parameter_symbols, self.parameter_values))
        df.loc[:, self.name()] = df.eval(self.string,
                                         global_dict=bla)
        return df

    def pre(self, df):
        df.loc[:, 'r_3d_nn'] = np.sqrt(df['x_3d_nn']**2 + df['y_3d_nn']**2)
        return df


for mass, params in FV_CONFIGS:
    name = 'FiducialTestEllips' + str(int(mass))
    c = type(name, (FiducialTestEllips,), dict())
    c.parameter_values = params
    locals()[name] = c


class FiducialFourLeafClover1250kg(StringLichen):
    """Fiducial volume cut: Four leaf Clover

    Our FV is constraint by two depth planes (4 cm above the gate, 9 cm below the gate)
    and a curved surface which stays 4 cm from the measured walls of the tpc.

    The fidicual volume cut defines the region in depth and radius that we
    trust and could use for the first science run. This is the region where
    we still expect the background distribution is flat.

    For the phi dependent shape we took the 210Po data from wall events and
    calculated where the ... percentile of events leaking in. For the angle
    the edge of the event distribution for different z slices where taken.
    The angel was taken so that both the lower and upper part of the FV stay a similar
    distance away from the edge.

    This version of the cut is based pax v6.4 bg run 0 data. See the
    note first results fiducial volume note for the study of the definition.

    Contact: Sander breur <sanderb@nikhef.nl>

    """
    version = 1

    string = "(-92.9 < z) & (z < -9) & (r_phi < r_max)"

    def pre(self, df):

        # first get the points from 210Po
        # open file and get text
        rho_phi_filename = os.path.join(DATA_DIR,
                                        'R_phi_curve_360points.txt')
        with open(rho_phi_filename) as file:
            text = file.readlines()
        # get value per line
        phi_values = []
        r_values = []
        for line in text:
            phi_values.append(float(line.split()[0]))
            r_values.append(float(line.split()[1]))

        # Set values needed for phi dependent radius
        phi_values = np.array(phi_values)
        r_values = np.array(r_values)
        # this is the average radius for the shape, this we scale
        average_radius_egg = np.average(r_values)

        # Set user defined values for the FV:
        # Set the radius and angle
        radius_scaling_value = 41  # cm # this sets the average radius
        radius_offset_value = 1  # cm # this sets the angle
        # Set the height
        depth_upper_bound = -9  # cm - exlude all gamma's
        depth_lower_bound = -96.9 + 4  # cm - stay away from the cathode
        max_height = depth_upper_bound - depth_lower_bound

        # Go to polar coordinates
        def cart2pol(x_value, y_value):
            """This is a simple function to change coordinate system.
            """
            rho = np.sqrt(x_value ** 2 + y_value ** 2)
            phi = np.arctan2(y_value, x_value)
            return (rho, phi)

        # Find argument of nearest value in array
        def find_nearest(array, values):
            """This is a simple function to find the argument of a value in an array.
            """
            indices = np.abs(np.subtract.outer(array, values)).argmin(0)
            return indices

        # Get the dep max radius for a FV in R with an angle set by r_offset
        # takes depth array [cm], Max radius [cm], radius offset [cm],
        # total height of cylinder [cm], center of cylinder in depth [cm]
        def coffee_r(z_value, R, r_offset, height, z_center):
            """This make the radius depth dependent. For a given r_offset it increases
            the top radius by r_offset and decreases the bottom radius by r_offset while
            keeping a straight line in the R2-Z space to keep the volume the same.
            """
            return np.sqrt((((R + r_offset) ** 2 - (R - r_offset) ** 2) / height) * (z_value - z_center + (height / 2)) + (
                R - r_offset) ** 2)  # returns radius array [cm]

        # Rho from data
        df.loc[:, 'r_phi'] = cart2pol(df['x'], df['y'])[0]
        # Max Rho
        df.loc[:, 'r_max'] = ((radius_scaling_value / average_radius_egg) *
                              coffee_r(df['z'],
                                       r_values[find_nearest(phi_values, cart2pol(df['x'], df['y'])[1])],
                                       radius_offset_value,
                                       max_height,
                                       -max_height / 2 + depth_upper_bound))
        return df


class AmBeFiducial(StringLichen):
    """AmBe Fiducial volume cut.
    This uses the same Z cuts as the 1T fiducial cylinder, but a wider allowed range in R to maximize the number of nuclear recoils.
    There is a third cut on the distance to the source, so that we cut away background ER.
    Link to note:
    https://xecluster.lngs.infn.it/dokuwiki/lib/exe/fetch.php?media=xenon:xenon1t:hogenbirk:nr_band_sr0.html

    Contact: Erik Hogenbirk <ehogenbi@nikhef.nl>

    Position updated to reflect correct I-Belt 1 position. Link to Note:xenon:xenon1t:analysis:dominick:sr1_ambe_check.
    """
    version = 2
    string = "(distance_to_source < 103.5) & (-92.9 < z) & (z < -9) & (sqrt(x*x + y*y) < 42.00)"

    def pre(self, df):
        source_position = (97, 43.5, -50)
        df.loc[:, 'distance_to_source'] = ((source_position[0] - df['x']) ** 2 +
                                           (source_position[1] - df['y']) ** 2 +
                                           (source_position[2] - df['z']) ** 2) ** 0.5
        return df


class InteractionExists(StringLichen):
    """Checks that there was a pairing of S1 and S2.

    Contact: Christopher Tunnell <tunnell@uchicago.edu>
    """
    version = 0
    string = "0 < cs1"


class InteractionPeaksBiggest(StringLichen):
    """Ensuring main peak is larger than the other peak

    (Should not be a big requirement for pax_v6.5.0)

    Contact: Christopher Tunnell <tunnell@uchicago.edu>
    """
    version = 0
    string = "(s1 > largest_other_s1) & (s2 > largest_other_s2)"


class S1LowEnergyRange(RangeLichen):
    """For isolating the low-energy band.
    Just an energy selection.
    Contact: Christopher Tunnell <tunnell@uchicago.edu>
    """
    version = 0
    allowed_range = (0, 200)
    variable = 'cs1'


class S1MaxPMT(StringLichen):
    """Cut events which have a high fraction of the area in a single PMT

    Cuts events which are mostly seen by one PMT. These events could be for
    example afterpulses or light emission. This is the 99% quantile fit using
    pax 6.4.2 on Rn220.

    xenon:xenon1t:yuehuan:analysis:0sciencerun_s1_pmtmax

    Contact: Julien Wulf <jwulf@physik.uzh.ch>
    """
    version = 0
    string = "s1_largest_hit_area < 0.052 * s1 + 4.15"


class S1PatternLikelihood(ManyLichen):
    """Reject accidendal coicident events from lone s1 and lone s2.

    Details of the likelihood and cut definitions can be seen in the following notes.
       SR0: xenon:xenon1t:analysis:summary_note:s1_pattern_likelihood_cut
       SR1: xenon:xenon1t:kazama:s1_pattern_cut_sr1,
            xenon:xenon1t:kazama:s1_pattern_cut_sr1#update_2018_jan_24th

    Requires PositionReconstruction minitrees (hax#174).
    Contact: Shingo Kazama <kazama@physik.uzh.ch>
    """
    version = 3

    def __init__(self):
        self.lichen_list = [self.S1TopPatternLikelihood(),
                            self.S1BottomPatternLikelihood()]

    class S1TopPatternLikelihood(Lichen):
        """S1PatternLikelihood cut based on the top PMT array
        """

        def _process(self, df):
            s1t = df['s1'] * df['s1_area_fraction_top']
            df.loc[:, self.name()] = (df['s1_pattern_fit_hax'] - df['s1_pattern_fit_bottom_hax'] <
                                      13.0 + 2.3 * s1t**0.5 + 8.0 * s1t - 1.0 * s1t**1.5 + 0.04 * s1t**2.0)
            return df

    class S1BottomPatternLikelihood(Lichen):
        """S1PatternLikelihood cut based on the bottom PMT array
        """

        def _process(self, df):
            s1b = df['s1'] * (1. - df['s1_area_fraction_top'])
            df.loc[:, self.name()] = (df['s1_pattern_fit_bottom_hax'] < - 10.5 + 21.9 * s1b**0.5 +
                                      1.44 * s1b - 0.21 * s1b**1.5 + 0.0064 * s1b**2.0)
            return df


class S1Width(StringLichen):
    """Reject accidendal coicidence events from lone s1 and lone s2.
    This cut is optimized to remove anomalous leakage (probably AC) candidates found in Rn220 SR1 data.
    Details of the cut definition and acceptance can be seen in the following note.
    xenon:xenon1t:analysis:sciencerun1:anomalous_background#s1_width_cut_for_removing_remaining_ac_events

    Requires Extended minitrees.
    Contact: Shingo Kazama <kazama@physik.uzh.ch>
    """

    version = 1
    string = "s1_range_90p_area < 251.528247 + 11.50 * s1**1.171407 * exp(-0.057395 * s1)"


class S1AreaUpperInjectionFraction(StringLichen):
    """Reject accidendal coicidence events happened near the upper Rn220 injection point (near PMT 131)

    Details of the cut definition and acceptance can be seen in the following notes.
    xenon:xenon1t:analysis:sciencerun1:anomalous_background#signal_area_fraction_near_rn220_injection_points

    Requires PositionReconstruction minitrees.
    Contact: Shingo Kazama <kazama@physik.uzh.ch>
    """

    version = 1
    string = "s1_area_upper_injection_fraction < 0.0865 + 1.205 / (s1**0.83367)"


class S1AreaLowerInjectionFraction(StringLichen):
    """Reject accidendal coicidence events happened near the lower Rn220 injection point (near PMT 243)

    Details of the cut definition and acceptance can be seen in the following notes.
    xenon:xenon1t:analysis:sciencerun1:anomalous_background#signal_area_fraction_near_rn220_injection_points

    Requires PositionReconstruction minitrees.
    Contact: Shingo Kazama <kazama@physik.uzh.ch>
    """

    version = 0
    string = "s1_area_lower_injection_fraction < 0.0550 + 1.56 / (s1**0.87000)"


class S2AreaFractionTop(Lichen):
    """Cuts events with an unusual fraction of S2 on top array.

    Primarily cuts gas events with a particularly large S2 AFT, also targets some
    strange / junk / other events with a low AFT.

    This cut has been checked on S2 ranges between 0 and 50 000 pe.

    Described in the note at: xenon:xenon1t:analysis:firstresults:s2_aft_cut_summary

    Contact: Adam Brown <abrown@physik.uzh.ch>
    """

    def _process_v2(self, df):
        """This is a simple range cut which was chosen by eye.
        """
        allowed_range = (0.5, 0.72)
        aft_variable = 's2_area_fraction_top'
        df.loc[:, self.name()] = ((df[aft_variable] < allowed_range[1]) &
                                  (df[aft_variable] > allowed_range[0]))
        return df

    def _process_v3(self, df):
        """This is a more complex and much tighter cut than version 2 from fitting
        the distribution in slices in S2 space and choosing the 0.5% and 99.5% quantile
        for each fit to give a theoretical acceptance of 99%.
        """

        def upper_limit_s2_aft(s2):
            return 0.6177399420527526 + 3.713166211522462e-08 * s2 + 0.5460484265254656 / np.log(s2)

        def lower_limit_s2_aft(s2):
            return 0.6648160611018054 - 2.590402853814859e-07 * s2 - 0.8531029789184852 / np.log(s2)

        aft_variable = 's2_area_fraction_top'
        s2_variable = 's2'
        df.loc[:, self.name()] = ((df[aft_variable] <
                                   upper_limit_s2_aft(df[s2_variable])) &
                                  (df[aft_variable] >
                                   lower_limit_s2_aft(df[s2_variable])))

        return df

    def __init__(self, version=2):
        self.version = version
        if version not in [2, 3]:
            raise ValueError('Only versions 2 and 3 are implemented')

    def _process(self, df):
        if self.version == 2:
            return self._process_v2(df)
        elif self.version == 3:
            return self._process_v3(df)
        else:
            raise ValueError('Only versions 2 and 3 are implemented')


class CS2AreaFractionTop(ManyLichen):
    """cS2 area fraction top cut

    Designed to target gas events.
    The acceptance is 99% by design.
    Valid in S2 range 0-10000

    See the note at xenon:xenon1t:adam:s2aft:sr1_cs2_cut
    """
    version = 0

    class CS2AreaFractionTopUpper(StringLichen):
        """cS2 AFT upper bound
        """
        string = 'cs2_aft < 0.63756073 + 1.42873942 / sqrt(s2)'

    class CS2AreaFractionTopLower(StringLichen):
        """cS2 AFT lower bound
        """
        string = 'cs2_aft > 0.62752992 - 1.79928264 / sqrt(s2)'

    lichen_list = [
        CS2AreaFractionTopUpper(),
        CS2AreaFractionTopLower()
    ]

    def pre(self, df):
        df.loc[:, 'cs2_aft'] = df['cs2_top'] / df['cs2']
        return df


class CS2AreaFractionTop96p(StringLichen):
    """cS2 area fraction top cut with 96% acceptance

    Designed to strongly target gas events, removing all
    those found in calibration samples at the top of the TPC.

    See the note at xenon:xenon1t:adam:s2aft:sr1_cs2_cut
    """
    string = 'cs2_aft < 0.63594139 + 0.912103 / sqrt(s2) | z < -9'


class S2SingleScatter(Lichen):
    """Check that largest other S2 area is smaller than some bound.

    The single scatter is to cut an event if its largest_other_s2 is too large.
    As the largest_other_s2 takes a greater value when they originated from some real scatters
    in comparison, those from photo-ionization in single scatter cases would be smaller.

    https://xecluster.lngs.infn.it/dokuwiki/doku.php?id=xenon:xenon1t:analysis:firstresults:cut:s2single

    Contact: Tianyu Zhu <tz2263@columbia.edu>
    """

    version = 4
    allowed_range = (0, np.inf)
    variable = 'temp'

    @classmethod
    def other_s2_bound(cls, s2_area):
        rescaled_s2_0 = s2_area * 0.00832 + 72.3
        rescaled_s2_1 = s2_area * 0.03 - 109

        another_term_0 = 1 / (np.exp((s2_area - 23300) * 5.91e-4) + 1)
        another_term_1 = 1 / (np.exp((23300 - s2_area) * 5.91e-4) + 1)

        return rescaled_s2_0 * another_term_0 + rescaled_s2_1 * another_term_1

    def _process(self, df):
        largest_other_s2_is_nan = np.isnan(df.largest_other_s2)
        df.loc[:, self.name()] = largest_other_s2_is_nan | (df.largest_other_s2 < self.other_s2_bound(df.s2))
        return df


class S2SingleScatterSimple(StringLichen):
    """Check that largest other S2 area is smaller than some bound.

    It's the low energy limit of the S2SingleScatter Cut
    applies to S2 < 20000

    https://xecluster.lngs.infn.it/dokuwiki/doku.php?id=xenon:xenon1t:analysis:firstresults:cut:s2single

    Contact: Tianyu Zhu <tz2263@columbia.edu>
    """
    version = 2
    string = '(~ (largest_other_s2 > 0)) | (largest_other_s2 < s2 * 0.00832 + 72.3)'


class S2PatternLikelihood(StringLichen):
    """Reject poorly reconstructed S2s and multiple scatters.

    Details of the likelihood can be seen in the following note. Here, 98
    quantile acceptance line estimated with Rn220 data (pax_v6.4.2) is used.

       xenon:xenon1t:analysis:firstresults:s2_pattern_likelihood_cut

    Requires Extended minitrees.

    Contact: Bart Pelssers  <bart.pelssers@fysik.su.se> Tianyu Zhu  <tz2263@columbia.edu>
    """
    version = 1
    string = "s2_pattern_fit < 0.0390 * s2 + 609 * s2**0.0602 - 666"


class S2Threshold(StringLichen):
    """The S2 energy at which the trigger is perfectly efficient.

    See: https://xecluster.lngs.infn.it/dokuwiki/doku.php?id=xenon:xenon1t:analysis:firstresults:daqtriggerpaxefficiency

    Contact: Jelle Aalbers <aalbers@nikhef.nl>
    """
    version = 1
    string = "200 < s2"


class S2Width(Lichen):
    """S2 Width cut based on diffusion model
    The S2 width cut compares the S2 width to what we could expect based on its depth in the detector. The inputs to
    this are the drift velocity and the diffusion constant. The allowed variation in S2 width is greater at low
    energy (since it is fluctuating statistically) Ref: (arXiv:1102.2865)
    It should be applicable to data regardless of if it ER or NR;
    above cS2 = 1e5 pe ERs the acceptance will go down due to track length effects.
    around S2 = 1e5 pe there are beta-gamma merged peaks from Pb214 that extends the S2 width
    Tune the diffusion model parameters based on fax data according to note:
    https://xe1t-wiki.lngs.infn.it/doku.php?id=xenon:xenon1t:sim:notes:tzhu:width_cut_tuning#toy_fax_simulation
    Contact: Tianyu <tz2263@columbia.edu>, Yuehuan <weiyh@physik.uzh.ch>, Jelle <jaalbers@nikhef.nl>
    """
    version = 6

    diffusion_constant = 25.26 * ((units.cm)**2) / units.s
    v_drift = 1.440 * (units.um) / units.ns
    scg = 23.0  # s2_secondary_sc_gain in pax config
    scw = 258.41  # s2_secondary_sc_width median
    SigmaToR50 = 1.349
    DriftTimeFromGate = 1.6 * units.us

    def s2_width_model(self, drift_time):
        """Diffusion model
        """
        return np.sqrt(2 * self.diffusion_constant * (drift_time - self.DriftTimeFromGate) / self.v_drift ** 2)

    def _process(self, df):
        df.loc[:, self.name()] = True  # Default is True
        mask = df.drift_time > self.DriftTimeFromGate
        df.loc[mask, 'nElectron'] = np.clip(df.loc[mask, 's2'], 0, 5000) / self.scg
        df.loc[mask, 'normWidth'] = (np.square(df.loc[mask, 's2_range_50p_area'] / self.SigmaToR50) -
                                     np.square(self.scw)) / np.square(self.s2_width_model(df.loc[mask, 'drift_time']))
        df.loc[mask, self.name()] = chi2.logpdf(df.loc[mask, 'normWidth'] * (df.loc[mask, 'nElectron'] - 1),
                                                df.loc[mask, 'nElectron']) > - 14
        return df

    def post(self, df):
        for temp_column in ['nElectron', 'normWidth']:
            if temp_column in df.columns:
                df.drop(temp_column, 1, inplace=True)
        return df


class S1SingleScatter(Lichen):
    """Requires only one valid interaction between the largest S2, and any S1 recorded before it.

    The S1 cut checks that any possible secondary S1s recorded in a waveform, could not have also
    produced a valid interaction with the primary S2. To check whether an interaction between the
    second largest S1 and the largest S2 is valid, we use the S2Width cut. If the event would pass
    the S2Width cut, a valid second interaction exists, and we may have mis-identified which S1 to
    pair with the primary S2. Therefore we cut this event. If it fails the S2Width cut the event is
    not removed.

    Current version is developed on calibration data (pax v6.8.0). It is described in this note:
    https://xecluster.lngs.infn.it/dokuwiki/doku.php?id=xenon:xenon1t:jacques:s1_single_scatter_cut_sr1

    It should be applicable to data regardless whether it is ER or NR.

    Contact: Jacques Pienaar, <jpienaar@uchicago.edu>
    """

    version = 4
    s2width = S2Width

    def _process(self, df):
        df.loc[:, self.name()] = True  # Default is True
        mask = df.alt_s1_interaction_drift_time > self.s2width.DriftTimeFromGate
        alt_n_electron = np.clip(df.loc[mask, 's2'], 0, 5000) / self.s2width.scg

        # Alternate S1 relative width
        alt_rel_width = np.square(df.loc[mask,
                                         's2_range_50p_area'] / self.s2width.SigmaToR50) - np.square(self.s2width.scw)
        alt_rel_width /= np.square(self.s2width.s2_width_model(self.s2width,
                                                               df.loc[mask, 'alt_s1_interaction_drift_time']))

        alt_interaction_passes = chi2.logpdf(alt_rel_width * (alt_n_electron - 1), alt_n_electron) > - 20

        df.loc[mask, (self.name())] = True ^ alt_interaction_passes

        return df


class S1AreaFractionTop(StringLichen):
    '''S1 area fraction top cut

    Uses a modified version of scipy.stats.binom_test to compute a p-value based on the
    observed number of s1 photons in the top array, given the expected probability (derived
    from Kr83m 32 keV line) that a photon at the event's (x,y,z) makes it to the top array.
    Modifications made to original algorithm implemented in pax increase sensitivity for small s1s.
    Algorithm imported in PositionReconstruction treemaker using corrected positions to calculate
    p-value.

    Requires PositionReconstruction minitrees.

    note: https://xe1t-wiki.lngs.infn.it/doku.php?id=xenon:xenon1t:darryl:xe1t_s1_aft_map
    also https://xe1t-wiki.lngs.infn.it/doku.php?id=xenon:xenon1t:darryl:s1_aft_update

    Contact: Darryl Masson, dmasson@purdue.edu
             Shingo Kazama, kazama@physik.uzh.ch
    '''
    version = 4
    string = "s1_area_fraction_top_probability_hax > 0.001"


class PreS2Junk(StringLichen):
    """Cut events with lot of peak area before main S2

    SR0: https://xe1t-wiki.lngs.infn.it/doku.php?id=xenon:xenon1t:yuehuan:analysis:0sciencerun_signal_noise
    SR1: https://xe1t-wiki.lngs.infn.it/doku.php?id=xenon:xenon1t:julien:analysis:sciencerun1:s1_noise_cut

    Contact: Julien Wulf <jwulf@physik.uzh.ch>
    """
    version = 1
    string = "area_before_main_s2 - s1 < 300"


class MuonVeto(ManyLichen):
    """Remove events in coincidence with Muon Veto triggers and when MV off.

    Requires Proximity minitrees.

    https://xe1t-wiki.lngs.infn.it/doku.php?id=xenon:xenon1t:analysis:mv_cut_sr1

    Contact: Andrea Molinario <andrea.molinario@lngs.infn.it>
    """
    version = 3

    def __init__(self):
        self.lichen_list = [self.MuonVetoOn(),
                            self.MuonVetoCoincidence()]

    class MuonVetoCoincidence(StringLichen):
        """Checks the distance in time (ns) between a reference position inside the waveform
        and the nearest MV trigger.
        The event is excluded if the nearest MV trigger falls in a [-2ms,+3ms] time window
        with respect to the reference position.
        """

        string = "nearest_muon_veto_trigger < -2e6 | nearest_muon_veto_trigger > 3e6"

    class MuonVetoOn(StringLichen):
        """Remove events when MV was not working (abs(nearest_muon_veto_trigger)>20 s).
        """

        string = "nearest_muon_veto_trigger > -2e10 & nearest_muon_veto_trigger < 2e10"


class KryptonMisIdS1(StringLichen):
    """Remove events where the 32 keV S1 of Kr83m decay is identified as an S2.
    These events appear above the ER band since the S1 is from the 9 keV decay
    but the S2 is combined for a 41 keV event.
    See the note:
    https://xe1t-wiki.lngs.infn.it/doku.php?id=xenon:xenon1t:adam:inelastic:cuts:kr_contamination:mis_ided_s1
    Contact: Adam Brown <abrown@physik.uzh.ch>
    """
    version = 0
    string = "largest_other_s2 < 100 | largest_other_s2_delay_main_s1 < -3000 | largest_other_s2_delay_main_s1 > 0"


class Flash(Lichen):
    """Cuts events within a flash. This is defined as the width were the BUSY on channel is "high".
    In addition an extended time-window around the flash is removed as well.
    The length of the extended time-window is not finalized yet
    Needs FlashIdentification minitree
    Information: https://xe1t-wiki.lngs.infn.it/doku.php?id=xenon:xenon1t:analysis:sciencerun1:flashercut
    Contact: Oliver Wack <oliver.wack@mpi-hd.mpg.de>
    """

    version = 0

    def _process(self, df):
        df.loc[:, self.name()] = ((df['inside_flash'] == False) &
                                  ((df.nearest_flash != df.nearest_flash) |
                                   (df['nearest_flash'] > 120e9) |
                                   (df['nearest_flash'] < (-10e9 - df['flashing_width'] * 1e9))
                                   )
                                  )
        return df


class PosDiff(Lichen):
    """
    Note: https://xe1t-wiki.lngs.infn.it/doku.php?id=xenon:xenon1t:analysis:sr1:pos_cut_v4
    This cut is defined for removing the events with large position difference between NN and TPF alogrithm,
    which can partly remove wall leakage events due to the small size of S2.
    Contact: Yuehuan Wei <ywei@physics.ucsd.edu>, Tianyu Zhu <tz2263@columbia.edu>
    """
    version = 4

    def _process(self, df):
        df.loc[:, self.name()] = (np.sqrt((df['x_observed_nn'] - df['x_observed_tpf'])**2 +
                                          (df['y_observed_nn'] - df['y_observed_tpf'])**2) <
                                  2429.322 * np.exp(-np.log10(df.s2) / 0.362) + 1.587)
        return df


class SingleElectronS2s(Lichen):  # noqa
    """To classify S1s from single electron S2s. Features (area, area_fraction_top, rise_time, range_90p_area) from
    S1 and single electron S2s samples are used to train a Gradient-BDT and Random-Forest classifier. A weight average
    voting was then used to distinguish the two samples and cut is defined in this new parameter space.
    Information: xenon:xenon1t:analysis:subgroup:cuts:meetings:20180126:se_classification
    Contact: Fei Gao <feigao.ge@gmail.com>
    """

    version = 5

    def _process(self, df):

        # Random forest classifier
        forest_filename = os.path.join(DATA_DIR, 'XENON1T_random_forest_peak_classifier_02052018.pkl')
        forest_load = pickle.load(open(forest_filename, 'rb'))  # noqa

        # Gradient Boosted Decesion Tree classifier
        gbdt_filename = os.path.join(DATA_DIR, 'XENON1T_gradient_bdt_peak_classifier_02052018.pkl')
        gbdt_load = pickle.load(open(gbdt_filename, 'rb'))  # noqa

        def _classifier_soft(features):
            return 0.5 * forest_load.predict_proba(features) + 0.5 * gbdt_load.predict_proba(features)

        df.loc[:, 'ses2prob'] = _classifier_soft(df[['s1', 's1_area_fraction_top', 's1_rise_time',
                                                     's1_range_90p_area']])[:, 1]

        cut_threshold = 0.9

        # current model is trained by data with S1 < 70PE and S1 width < 450PE
        df.loc[:, self.name()] = (((df['ses2prob'] <= cut_threshold) & (df['s1_range_90p_area'] < 450)) |
                                  (df['s1'] > 70))

        return df
